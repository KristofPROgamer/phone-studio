"""CPU-only adapter tests: local image fixtures and mocked LLM replies, no model."""
import asyncio
import base64
import io
import json
import tempfile
import time
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiohttp import web
import aiohttp
from PIL import Image

from router.llm import LLMClient, LLMUnavailable, MAX_REPLY_BYTES, MAX_TEXT, TAG_SCHEMA, PLAN_SCHEMA


def pinned_schema(payload):
    """The b11146 parser reads only response_format.json_schema.schema.

    Its missing-schema fallback is a generic object. The mock deliberately rejects
    that fallback, so the old sibling `schema` cannot accidentally pass the tests.
    """
    response_format = payload.get("response_format", {})
    return response_format.get("json_schema", {}).get("schema", {"type": "object"})


class Chunks:
    def __init__(self, chunks):
        self.chunks = chunks

    async def iter_chunked(self, _size):
        for chunk in self.chunks:
            yield chunk


class Response:
    def __init__(self, chunks, status=200):
        self.status = status
        self.content = Chunks(chunks)


class LLMTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.paths = {}
        self.candidates = []
        for index, color in enumerate(("red", "green", "blue")):
            asset = f"asset-{index}"
            path = self.root / f"{asset}.png"
            Image.new("RGB", (64, 48), color).save(path)
            self.paths[asset] = path
            self.candidates.append({"candidateId": f"candidate-{index}", "assetId": asset})
        self.client = LLMClient("http://127.0.0.1:8081")
        self.request = {"operation": "generate", "originalPrompt": "two birds beside one tree",
            "negativePrompt": "people", "requestId": "request-test", "options": {}}

    async def asyncTearDown(self):
        await self.client.close()
        self.temp.cleanup()

    def review_reply(self):
        return {"winnerCandidateId": "candidate-1", "reason": "Only this image has two birds.",
            "scores": [{"candidateId": item["candidateId"], "adherence": 8,
                        "preservation": 7, "quality": 9, "reason": "Visible matching details."}
                       for item in self.candidates]}

    def plan_reply(self):
        return {"mode": "replace", "positivePrompt": "one blue bird", "negativePrompt": "people",
            "denoise": 0.8, "targetText": "bird", "boxes": [[0.1, 0.1, 0.8, 0.8]],
            "points": [[0.5, 0.5, 1]], "preservedFeatures": ["tree"], "warnings": []}

    @asynccontextmanager
    async def local_server(self, handler, *, health=True):
        app = web.Application()
        app.router.add_post("/v1/chat/completions", handler)
        if health:
            async def health_response(_):
                return web.json_response({"status": "ok"})

            async def props_response(_):
                return web.json_response({"modalities": {"vision": True}})

            app.router.add_get("/health", health_response)
            app.router.add_get("/props", props_response)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        client = LLMClient(f"http://127.0.0.1:{port}", api_key="test-private-key")
        try:
            yield client
        finally:
            await client.close()
            await runner.cleanup()

    async def test_review_sends_actual_three_images_and_original_request(self):
        self.client._completion = AsyncMock(return_value=self.review_reply())
        result = await self.client.review(self.request, self.candidates, self.paths)
        self.assertEqual(result["status"], "selected")
        self.assertEqual(result["winnerCandidateId"], "candidate-1")
        args = self.client._completion.call_args.args
        self.assertIn(self.request["originalPrompt"], args[2][0]["text"])
        images = [item for item in args[2] if item["type"] == "image_url"]
        self.assertEqual(len(images), 3)
        colors = []
        for item in images:
            image = Image.open(io.BytesIO(base64.b64decode(item["image_url"]["url"].split(",", 1)[1])))
            colors.append(image.getpixel((0, 0)))
        self.assertEqual(colors, [(255, 0, 0), (0, 128, 0), (0, 0, 255)])

    async def test_unknown_winner_is_unavailable_without_fallback(self):
        reply = self.review_reply()
        reply["winnerCandidateId"] = "invented-id"
        self.client._completion = AsyncMock(return_value=reply)
        result = await self.client.review(self.request, self.candidates, self.paths)
        self.assertEqual(result["status"], "unavailable")
        self.assertNotIn("winnerCandidateId", result)

    async def test_duplicate_score_ids_cannot_select(self):
        reply = self.review_reply()
        reply["scores"][2]["candidateId"] = "candidate-1"
        self.client._completion = AsyncMock(return_value=reply)
        result = await self.client.review(self.request, self.candidates, self.paths)
        self.assertEqual(result["status"], "unavailable")
        self.assertNotIn("winnerCandidateId", result)

    async def test_nan_score_cannot_select(self):
        reply = self.review_reply()
        reply["scores"][0]["adherence"] = float("nan")
        self.client._completion = AsyncMock(return_value=reply)
        self.assertEqual((await self.client.review(self.request, self.candidates, self.paths))["status"], "unavailable")

    async def test_lower_adherence_winner_is_inconsistent_not_replaced(self):
        reply = self.review_reply()
        reply["scores"][0]["adherence"] = 10
        self.client._completion = AsyncMock(return_value=reply)
        result = await self.client.review(self.request, self.candidates, self.paths)
        self.assertEqual(result["status"], "unavailable")
        self.assertNotIn("winnerCandidateId", result)

    async def test_edit_review_includes_source_and_original_instruction(self):
        self.request.update(operation="edit", sourceAssetId="asset-0", editInstruction="turn only the bird blue")
        self.client._completion = AsyncMock(return_value=self.review_reply())
        await self.client.review(self.request, self.candidates, self.paths)
        content = self.client._completion.call_args.args[2]
        self.assertEqual(sum(item["type"] == "image_url" for item in content), 4)
        self.assertIn(self.request["editInstruction"], content[0]["text"])

    async def test_review_failure_and_missing_source_never_invent_winner(self):
        self.client._completion = AsyncMock(side_effect=LLMUnavailable("Timed out."))
        result = await self.client.review(self.request, self.candidates, self.paths)
        self.assertEqual(result["status"], "unavailable")
        self.assertNotIn("winnerCandidateId", result)
        self.request.update(operation="edit", sourceAssetId="missing")
        self.assertEqual((await self.client.review(self.request, self.candidates, self.paths))["status"], "unavailable")

    async def test_disabled_review_does_not_touch_images_or_llm(self):
        self.request["options"]["reviewCandidates"] = False
        self.client._completion = AsyncMock()
        result = await self.client.review(self.request, self.candidates, {})
        self.assertEqual(result["status"], "disabled")
        self.client._completion.assert_not_called()

    async def test_enhancement_falls_back_to_original_on_invalid_output(self):
        self.client._completion = AsyncMock(return_value={"positiveTags": [], "warnings": []})
        result = await self.client.enhance(self.request)
        self.assertEqual(result["effectivePrompt"], self.request["originalPrompt"])
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(self.request["negativePrompt"], "people")

    async def test_cancelled_review_propagates_cancellation(self):
        self.client._completion = AsyncMock(side_effect=asyncio.CancelledError())
        with self.assertRaises(asyncio.CancelledError):
            await self.client.review(self.request, self.candidates, self.paths)

    async def test_chunked_json_read_handles_full_body_and_size_cap(self):
        data = await self.client._read_json(Response([b'{"sta', b'tus":', b'"ok"}']))
        self.assertEqual(data, {"status": "ok"})
        with self.assertRaises(LLMUnavailable):
            await self.client._read_json(Response([b"a" * MAX_REPLY_BYTES, b"b"]))

    async def test_expired_deadline_does_not_call_http(self):
        self.request["deadlineMillis"] = int((time.time() - 10) * 1000)
        with patch.object(self.client, "_http") as http:
            with self.assertRaises(LLMUnavailable):
                await self.client._completion(self.request, "system", [], {}, 10)
            http.assert_not_called()

    async def test_edit_plan_rejects_fractional_point_label_and_preserves_negatives(self):
        self.request.update(operation="edit", editInstruction="replace the bird")
        plan = {"mode": "replace", "positivePrompt": "one blue bird", "negativePrompt": "discard originals",
            "denoise": 0.8, "targetText": "bird", "boxes": [[0.1, 0.1, 0.8, 0.8]],
            "points": [[0.5, 0.5, 0.5]], "preservedFeatures": ["tree"], "warnings": []}
        self.client._completion = AsyncMock(return_value=plan)
        with self.assertRaises(LLMUnavailable):
            await self.client.plan_edit(self.request, self.paths["asset-0"])
        plan["points"][0][2] = 1
        result = await self.client.plan_edit(self.request, self.paths["asset-0"])
        self.assertEqual(result["negativePrompt"], "people")
        self.assertEqual(result["mode"], "replace")

    async def test_real_local_http_payload_serializes_and_limits_one_slot(self):
        state = {"active": 0, "peak": 0, "payloads": []}

        async def completion(request):
            payload = await request.json()
            self.assertEqual(request.headers["Authorization"], "Bearer test-private-key")
            if pinned_schema(payload) != TAG_SCHEMA:
                return web.json_response({"error": {"type": "invalid_request_error", "code": 400}}, status=400)
            state["payloads"].append(payload)
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
            await asyncio.sleep(0.02)
            state["active"] -= 1
            return web.json_response({"choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps({"positiveTags": ["2birds", "tree"], "warnings": []})}}]})

        app = web.Application()
        app.router.add_post("/v1/chat/completions", completion)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        client = LLMClient(f"http://127.0.0.1:{port}", api_key="test-private-key")
        try:
            results = await asyncio.gather(client.enhance(self.request), client.enhance(self.request))
            self.assertTrue(all(item["status"] == "enhanced" for item in results))
            self.assertEqual(state["peak"], 1)
            self.assertEqual(state["payloads"][0]["chat_template_kwargs"], {"enable_thinking": False})
            self.assertEqual(state["payloads"][0]["response_format"]["type"], "json_schema")
            self.assertEqual(pinned_schema(state["payloads"][0]), TAG_SCHEMA)
            self.assertNotIn("schema", state["payloads"][0]["response_format"])
            self.assertFalse(state["payloads"][0]["stream"])
        finally:
            await client.close()
            await runner.cleanup()

    async def test_deadline_includes_waiting_for_serial_slot(self):
        request = {**self.request, "deadlineMillis": int((time.time() + 0.03) * 1000)}
        await self.client._slot.acquire()
        try:
            with patch.object(self.client, "_http") as http:
                with self.assertRaises(LLMUnavailable):
                    await self.client._completion(request, "system", [], {}, 10)
                http.assert_not_called()
                self.assertEqual(self.client._last_inference["category"], "inference_deadline")
                self.assertEqual(self.client._last_inference["inferenceMillis"], 0)
                self.assertGreater(self.client._last_inference["queueMillis"], 0)
        finally:
            self.client._slot.release()

    async def test_pinned_contract_rejects_old_wrapper_and_accepts_all_tasks(self):
        payloads = []

        async def completion(request):
            payload = await request.json()
            schema = pinned_schema(payload)
            if not schema.get("required"):
                return web.json_response({"error": {"type": "invalid_request_error", "code": 400}}, status=400)
            payloads.append(payload)
            if "positiveTags" in schema["properties"]:
                self.assertEqual(schema, TAG_SCHEMA)
                reply = {"positiveTags": ["2birds", "tree"], "warnings": []}
            elif "mode" in schema["properties"]:
                self.assertEqual(schema, PLAN_SCHEMA)
                reply = self.plan_reply()
            else:
                self.assertEqual(schema["properties"]["winnerCandidateId"]["enum"],
                                 [item["candidateId"] for item in self.candidates])
                reply = self.review_reply()
            return web.json_response({"choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps(reply)}}], "usage": {"completion_tokens": 123}})

        async with self.local_server(completion) as client:
            # Confirm that this HTTP mock fails the exact former adapter payload.
            async with client._http().post(client.base_url + "/v1/chat/completions", json={
                    "response_format": {"type": "json_schema", "schema": TAG_SCHEMA}}) as response:
                self.assertEqual(response.status, 400)
            self.assertEqual((await client.enhance(self.request))["status"], "enhanced")
            edit = {**self.request, "operation": "edit", "sourceAssetId": "asset-0",
                    "editInstruction": "replace only the bird with a blue bird"}
            self.assertEqual((await client.plan_edit(edit, self.paths["asset-0"]))["mode"], "replace")
            self.assertEqual((await client.review(edit, self.candidates, self.paths))["status"], "selected")
            counts = [sum(part["type"] == "image_url" for part in payload["messages"][1]["content"])
                      for payload in payloads]
            self.assertEqual(counts, [0, 1, 4])
            health = await client.health()
            self.assertTrue(health["processReady"])
            self.assertTrue(health["ready"])
            self.assertEqual(health["inferenceStatus"], "succeeded")
            self.assertEqual(health["lastInference"]["outputTokens"], 123)
            self.assertEqual(health["lastInference"]["imageDimensions"], [[64, 48]] * 4)

    async def test_context_overflow_retains_four_images_and_never_invents_winner(self):
        seen = []

        async def completion(request):
            seen.append(await request.json())
            return web.json_response({"error": {"type": "exceed_context_size_error", "code": 400,
                "message": "PRIVATE original prompt and image data"}}, status=400)

        edit = {**self.request, "operation": "edit", "sourceAssetId": "asset-0",
                "editInstruction": "change only the bird"}
        async with self.local_server(completion) as client:
            with self.assertLogs("phone-studio-router.llm", level="INFO") as logs:
                result = await client.review(edit, self.candidates, self.paths)
            self.assertEqual(result["status"], "unavailable")
            self.assertNotIn("winnerCandidateId", result)
            self.assertEqual(sum(part["type"] == "image_url" for part in seen[0]["messages"][1]["content"]), 4)
            self.assertEqual(client._last_inference["category"], "context_overflow")
            self.assertEqual(client._last_inference["serverErrorType"], "exceed_context_size_error")
            self.assertEqual(client._last_inference["httpStatus"], 400)
            self.assertNotIn("PRIVATE", result["reason"])
            self.assertNotIn("PRIVATE", " ".join(logs.output))
            self.assertNotIn("data:image", " ".join(logs.output))

    async def test_long_text_is_preserved_and_oversize_is_explicit(self):
        seen = []

        async def completion(request):
            seen.append(await request.json())
            return web.json_response({"choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps({"positiveTags": ["two birds"], "warnings": []})}}]})

        original = "keep every instruction " * 500
        async with self.local_server(completion) as client:
            result = await client.enhance({**self.request, "originalPrompt": original})
            self.assertEqual(result["status"], "enhanced")
            self.assertEqual(json.loads(seen[0]["messages"][1]["content"][0]["text"])["originalRequest"], original)
            with self.assertRaises(LLMUnavailable) as error:
                await client.enhance({**self.request, "originalPrompt": "x" * (MAX_TEXT + 1)})
            self.assertEqual(error.exception.category, "context_overflow")
            self.assertEqual(len(seen), 1)
            self.assertEqual(client._last_inference["status"], "failed")

    async def test_error_categories_and_health_do_not_expose_response_text(self):
        state = {}

        async def completion(_):
            return web.json_response(state["body"], status=state["status"])

        cases = [
            (401, {"error": {"type": "authentication_error", "code": 401, "message": "PRIVATE key"}}, "authentication"),
            (503, {"error": {"type": "unavailable_error", "code": 503, "message": "PRIVATE prompt"}}, "server_rejection"),
            (500, {"error": {"type": ["PRIVATE"], "code": "PRIVATE", "message": "CUDA OOM PRIVATE"}}, "server_rejection"),
            (200, {"choices": [{"finish_reason": "length", "message": {"content": "PRIVATE unfinished"}}]}, "incomplete_output"),
            (200, {"choices": [{"finish_reason": "stop", "message": {
                "content": "", "reasoning_content": "PRIVATE reasoning"}}]}, "incomplete_output"),
            (200, {"choices": [{"finish_reason": "stop", "message": {"content": "PRIVATE invalid JSON"}}]}, "malformed_json"),
            (200, {"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]}, "invalid_task_fields"),
        ]
        async with self.local_server(completion) as client:
            initial = await client.health()
            self.assertTrue(initial["processReady"])
            self.assertEqual(initial["inferenceStatus"], "untested")
            for status, body, category in cases:
                with self.subTest(category=category, status=status):
                    state.update(status=status, body=body)
                    with self.assertLogs("phone-studio-router.llm", level="INFO") as logs:
                        result = await client.enhance(self.request)
                    self.assertEqual(result["status"], "unavailable")
                    self.assertEqual(result["effectivePrompt"], self.request["originalPrompt"])
                    health = await client.health()
                    self.assertTrue(health["processReady"])
                    self.assertFalse(health["ready"])
                    self.assertTrue(health["degraded"])
                    self.assertEqual(health["inferenceStatus"], "failed")
                    self.assertEqual(health["lastInference"]["category"], category)
                    self.assertIn("Last inference failed", health["message"])
                    self.assertNotIn("PRIVATE", json.dumps(health))
                    self.assertNotIn("PRIVATE", " ".join(logs.output))
                    self.assertNotIn("test-private-key", " ".join(logs.output))
                    self.assertNotIn(self.request["originalPrompt"], " ".join(logs.output))
            # A later validated task clears failure, rather than health doing so.
            state.update(status=200, body={"choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps({"positiveTags": ["two birds"], "warnings": []})}}]})
            await client.enhance(self.request)
            health = await client.health()
            self.assertTrue(health["ready"])
            self.assertTrue(health["processReady"])
            self.assertEqual(health["inferenceStatus"], "succeeded")
            self.assertFalse(health["degraded"])

    async def test_transport_failure_is_safe_and_not_reported_as_memory_failure(self):
        with patch.object(self.client, "_http", side_effect=aiohttp.ClientConnectionError("PRIVATE endpoint")):
            with self.assertLogs("phone-studio-router.llm", level="INFO") as logs:
                result = await self.client.enhance(self.request)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(self.client._last_inference["category"], "transport")
        self.assertNotIn("PRIVATE", " ".join(logs.output))
        self.assertNotIn("PRIVATE", " ".join(result["warnings"]))

    async def test_inference_deadline_is_distinct_from_waiting_for_slot(self):
        entered = asyncio.Event()

        async def completion(_):
            entered.set()
            await asyncio.sleep(0.15)
            return web.json_response({})

        async with self.local_server(completion) as client:
            request = {**self.request, "deadlineMillis": int((time.time() + 0.08) * 1000)}
            result = await client.enhance(request)
            self.assertTrue(entered.is_set())
            self.assertEqual(result["status"], "unavailable")
            self.assertEqual(client._last_inference["category"], "inference_deadline")
            self.assertGreater(client._last_inference["inferenceMillis"], 0)
            self.assertLess(client._last_inference["queueMillis"], client._last_inference["inferenceMillis"])

    async def test_post_completion_validation_failure_remains_visible(self):
        async def completion(_):
            reply = self.review_reply()
            reply["scores"][0]["adherence"] = 11
            return web.json_response({"choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps(reply)}}]})

        async with self.local_server(completion) as client:
            result = await client.review(self.request, self.candidates, self.paths)
            self.assertEqual(result["status"], "unavailable")
            self.assertEqual(client._last_inference["category"], "invalid_task_fields")
            self.assertEqual(client._last_inference["finishReason"], "stop")
            self.assertEqual(client._last_inference["httpStatus"], 200)
            health = await client.health()
            self.assertEqual(health["inferenceStatus"], "failed")
            self.assertTrue(health["processReady"])
            self.assertFalse(health["ready"])

    async def test_unvalidated_reply_does_not_advertise_assistant_ready(self):
        async def completion(_):
            return web.json_response({"choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps({"positiveTags": ["two birds"], "warnings": []})}}]})

        async with self.local_server(completion) as client:
            await client._completion(self.request, "system", [], TAG_SCHEMA, 1400)
            health = await client.health()
            self.assertTrue(health["processReady"])
            self.assertFalse(health["ready"])
            self.assertEqual(health["inferenceStatus"], "validating")
            await client.enhance(self.request)
            health = await client.health()
            self.assertTrue(health["ready"])
            self.assertEqual(health["inferenceStatus"], "succeeded")


if __name__ == "__main__":
    unittest.main()
