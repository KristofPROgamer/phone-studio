"""Actual loopback transport with fake Comfy endpoints; no generation/model calls."""
import asyncio
import io
import tempfile
import time
import unittest
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestServer
from PIL import Image

from router.config import Config, WorkerConfig
from router.workers import WorkerClient, WorkerFailure


class WorkerTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        directory = Path(self.temp.name)
        self.config = Config(directory / "local", directory / "drive", "router-secret", disk_reserve_bytes=0)
        self.posts, self.recoveries, self.cancelled, self.interrupted = 0, 0, [], 0
        self.runtime, self.mode = "runtime-1", "normal"
        self.received = []
        self.events = []
        self.prompt_id = "00000000-0000-0000-0000-000000000001"
        self.reply_image = io.BytesIO(); Image.new("RGB", (16, 16), "red").save(self.reply_image, format="PNG")
        routes = web.RouteTableDef()

        @web.middleware
        async def capture(request, handler):
            self.received.append((request.path, request.headers.get("X-Phone-Studio-Token"), request.headers.get("Authorization")))
            return await handler(request)

        @routes.get("/phone-studio/health")
        async def health(request):
            return web.json_response({"ok": True, "instanceId": self.runtime})

        @routes.get("/phone-studio/models")
        async def models(request):
            if self.mode == "models_rejected":
                return web.json_response({"error": "private worker-secret"}, status=403)
            return web.json_response({"checkpoints": ["model.safetensors"], "loras": []})

        @routes.post("/prompt")
        async def prompt(request):
            self.posts += 1
            self.payload = await request.json()
            if self.mode == "rejected":
                return web.json_response({"error": "private internal token worker-secret"}, status=400)
            if self.mode == "lost_reply":
                return web.Response(text="a tunnel interstitial", content_type="text/html")
            if self.mode == "reset_after_acceptance":
                self.runtime = "runtime-2"
                return web.Response(text="a tunnel interstitial", content_type="text/html")
            return web.json_response({"prompt_id": self.prompt_id})

        @routes.get("/phone-studio/latest-job")
        async def latest(request):
            self.recoveries += 1
            return web.json_response({"status": "done", "promptId": self.prompt_id, "requestId": request.query["requestId"]})

        @routes.get("/history/{promptId}")
        async def history(request):
            if self.mode == "history_auth":
                return web.json_response({"error": "private worker-secret"}, status=403)
            if self.mode == "history_http":
                return web.json_response({"error": "private worker-secret"}, status=400)
            if self.mode == "history_unreadable":
                return web.Response(text="private worker-secret", content_type="text/html")
            if self.mode == "history_invalid_entry":
                return web.json_response({self.prompt_id: []})
            if self.mode == "generation_error":
                return web.json_response({self.prompt_id: {"status": {"status_str": "error", "completed": True}}})
            return web.json_response({self.prompt_id: {"status": {"completed": True, "status_str": "success"},
                "outputs": {"7": {"images": [{"filename": "result.png", "subfolder": "", "type": "output"}]}}}})

        @routes.get("/ws")
        async def websocket(request):
            socket = web.WebSocketResponse()
            await socket.prepare(request)
            await socket.send_json({"type": "progress", "data": {"prompt_id": self.prompt_id, "value": 3, "max": 24}})
            await socket.send_json({"type": "execution_success", "data": {"prompt_id": self.prompt_id}})
            async for message in socket:
                pass
            return socket

        @routes.get("/view")
        async def view(request):
            if self.mode == "view_error":
                return web.json_response({"error": "private worker-secret"}, status=503)
            return web.Response(body=self.reply_image.getvalue(), content_type="image/png")

        @routes.post("/upload/image")
        async def upload(request):
            reader = await request.multipart()
            name = None
            async for part in reader:
                if part.name == "image":
                    name = part.filename
                await part.read()
            return web.json_response({"name": name, "subfolder": "", "type": "input"})

        @routes.get("/queue")
        async def queue(request):
            return web.json_response({"queue_pending": [[1, self.prompt_id]], "queue_running": []})

        @routes.post("/queue")
        async def remove(request):
            self.cancelled.append(await request.json())
            return web.json_response({})

        @routes.post("/interrupt")
        async def interrupt(request):
            self.interrupted += 1
            return web.json_response({})

        app = web.Application(middlewares=[capture]); app.add_routes(routes)
        self.server = TestServer(app); await self.server.start_server()
        self.worker = WorkerConfig("worker-1", "Worker", str(self.server.make_url("")).rstrip("/"), "studio", "tunnel-secret", "worker-secret")
        self.config.workers = (self.worker,)
        self.client = WorkerClient(self.config); await self.client.start()
        await self.client.probe(self.worker)

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()
        self.temp.cleanup()

    def record(self, **changes):
        result = {"requestId": "request-1", "clientId": "router-test", "runtimeId": "runtime-1", "promptId": None, "submissionAttempted": False}
        result.update(changes)
        return result

    async def change(self, fields, durable):
        self.events.append((fields, durable))

    async def test_transport_recovers_lost_reply_without_a_second_post(self):
        self.mode = "lost_reply"
        images = await self.client.render(self.worker, self.record(), {"1": {}}, True, self.change, time.monotonic() + 10)
        self.assertEqual(self.posts, 1)
        self.assertEqual(self.recoveries, 1)
        self.assertEqual(images[0]["filename"], "result.png")
        self.assertTrue(any(fields.get("submissionAttempted") and durable for fields, durable in self.events))
        self.assertTrue(all(token == "worker-secret" and auth.startswith("Basic ") for _, token, auth in self.received))
        self.assertNotIn("prompt_id", self.payload)  # No unverified caller-ID support.

    async def test_reset_during_uncertain_submission_is_not_replayed(self):
        self.mode = "reset_after_acceptance"
        with self.assertRaises(WorkerFailure) as caught:
            await self.client.render(self.worker, self.record(), {"1": {}}, False, self.change, time.monotonic() + 0.01)
        self.assertTrue(caught.exception.uncertain)
        self.assertEqual(self.posts, 1)
        self.assertEqual(self.recoveries, 0)

    async def test_confirmed_rejection_is_sanitized_and_does_not_recover(self):
        self.mode = "rejected"
        with self.assertRaises(WorkerFailure) as caught:
            await self.client.render(self.worker, self.record(), {"1": {}}, False, self.change, time.monotonic() + 10)
        self.assertFalse(caught.exception.uncertain)
        self.assertNotIn("worker-secret", str(caught.exception))
        self.assertEqual(self.posts, 1)
        self.assertEqual(self.recoveries, 0)

    async def test_resume_existing_prompt_follows_without_post(self):
        images = await self.client.render(self.worker, self.record(promptId=self.prompt_id, submissionAttempted=True), {"1": {}}, False, self.change, time.monotonic() + 10)
        self.assertEqual(len(images), 1)
        self.assertEqual(self.posts, 0)

    async def test_known_accepted_history_failure_can_resume_without_second_post(self):
        for mode in ("history_auth", "history_http", "history_unreadable", "history_invalid_entry"):
            with self.subTest(mode=mode):
                before = self.posts
                record = self.record()
                async def persist(fields, durable):
                    record.update(fields)
                    await self.change(fields, durable)
                self.mode = mode
                with self.assertRaises(WorkerFailure) as caught:
                    await self.client.render(self.worker, record, {"1": {}}, False, persist, time.monotonic() + 0.05)
                self.assertTrue(caught.exception.resume_only)
                self.assertFalse(caught.exception.uncertain)
                self.assertNotIn("worker-secret", str(caught.exception))
                self.assertEqual(self.posts, before + 1)
                self.assertTrue(record["submissionAttempted"])
                self.assertEqual(record["promptId"], self.prompt_id)
                self.mode = "normal"
                images = await self.client.render(self.worker, record, {}, False, persist, time.monotonic() + 5)
                self.assertEqual(images[0]["filename"], "result.png")
                self.assertEqual(self.posts, before + 1)

    async def test_finished_output_retrieval_failure_does_not_repeat_post(self):
        images = await self.client.render(self.worker, self.record(), {"1": {}}, False,
                                          self.change, time.monotonic() + 5)
        target = Path(self.temp.name) / "retried.png"
        self.mode = "view_error"
        with self.assertRaises(WorkerFailure) as caught:
            await self.client.collect(self.worker, images[0], target)
        self.assertTrue(caught.exception.resume_only)
        self.mode = "normal"
        await self.client.collect(self.worker, images[0], target)
        self.assertEqual(self.posts, 1)
        self.assertEqual(target.read_bytes(), self.reply_image.getvalue())

    async def test_catalog_rejection_retains_successful_authenticated_health_identity(self):
        self.mode = "models_rejected"
        result = await self.client.probe(self.worker)
        self.assertFalse(result["online"])
        self.assertEqual(result["runtimeId"], self.runtime)
        self.assertEqual(result["probeStage"], "catalog_rejected_or_unreachable")
        self.assertNotIn("worker-secret", result["message"])

    async def test_definite_history_generation_error_still_allows_targeted_new_render(self):
        self.mode = "generation_error"
        with self.assertRaises(WorkerFailure) as caught:
            await self.client.render(self.worker, self.record(), {"1": {}}, False,
                                     self.change, time.monotonic() + 5)
        self.assertFalse(caught.exception.resume_only)
        self.assertFalse(caught.exception.uncertain)
        self.assertEqual(self.posts, 1)

    async def test_progress_observer_exception_does_not_replace_authoritative_accepted_history(self):
        async def broken_observer(*args):
            raise RuntimeError("private worker-secret observer detail")
        self.client._watch = broken_observer
        with self.assertLogs("phone-studio-router.workers", level="WARNING") as captured:
            images = await self.client.render(self.worker, self.record(), {"1": {}}, False,
                                              self.change, time.monotonic() + 5)
        self.assertEqual(images[0]["filename"], "result.png")
        self.assertEqual(self.posts, 1)
        self.assertNotIn("worker-secret", " ".join(captured.output))
        self.assertTrue(any(fields.get("promptId") == self.prompt_id and durable for fields, durable in self.events))

    async def test_post_acceptance_queued_publication_failure_never_authorizes_new_graph(self):
        record = self.record()
        async def fail_publication(fields, durable):
            if "promptId" in fields:
                raise RuntimeError("synthetic queued-publication failure")
            record.update(fields)
        with self.assertRaises(WorkerFailure) as caught:
            await self.client.render(self.worker, record, {"1": {}}, False,
                                     fail_publication, time.monotonic() + 5)
        self.assertTrue(caught.exception.uncertain)
        self.assertTrue(caught.exception.resume_only)
        self.assertTrue(record["submissionAttempted"])
        self.assertIsNone(record["promptId"])
        self.assertEqual(self.posts, 1)

    async def test_upload_and_bounded_original_collection(self):
        source = Path(self.temp.name) / "source.png"
        source.write_bytes(self.reply_image.getvalue())
        name = await self.client.upload(self.worker, str(source), "mask")
        self.assertTrue(name.startswith("router-") and name.endswith("-mask.png"))
        target = Path(self.temp.name) / "copied.png"
        await self.client.collect(self.worker, {"filename": "result.png", "type": "output"}, target)
        self.assertEqual(target.read_bytes(), source.read_bytes())
        self.config.max_upload_bytes = 4
        with self.assertRaises(WorkerFailure):
            await self.client.collect(self.worker, {"filename": "result.png", "type": "output"}, target)

    async def test_old_worker_cancellation_only_deletes_named_queue_item(self):
        cancelled = await self.client.cancel(self.worker, self.record(promptId=self.prompt_id))
        self.assertTrue(cancelled)
        self.assertEqual(self.cancelled, [{"delete": [self.prompt_id]}])
        self.assertEqual(self.interrupted, 0)
