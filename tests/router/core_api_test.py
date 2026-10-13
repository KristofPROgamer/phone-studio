"""Actual loopback HTTP/WebSocket API with mock inference and temporary storage."""
import asyncio
import copy
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import aiohttp
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

from router.config import Config, WorkerConfig
from router.server import create_app
from router.service import RouterService


class NoWorkers:
    observed = {}
    async def start(self): pass
    async def close(self): pass
    async def probes(self, **kwargs): return []


class NoLLM:
    async def close(self): pass
    async def health(self):
        return {"ready": False, "model": "mock", "revision": "mock", "degraded": False, "message": "Unavailable"}


class RouterApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.config = Config(root / "local", root / "drive", "studio-secret", basic_user="studio", basic_password="tunnel-secret", disk_reserve_bytes=0)
        self.service = RouterService(self.config, workers=NoWorkers(), llm=NoLLM())
        # This API test keeps jobs accepted until explicitly updated; service
        # orchestration itself is tested through real CPU assets in core_service.
        self.service.schedule = lambda job_id: None
        self.client = TestClient(TestServer(create_app(self.config, self.service)))
        await self.client.start_server()
        self.headers = {"X-Phone-Studio-Token": "studio-secret", "Authorization": aiohttp.encode_basic_auth("studio", "tunnel-secret", encoding="latin1")}

    async def asyncTearDown(self):
        await self.client.close()
        self.temp.cleanup()

    def body(self):
        return {"schemaVersion": 2, "clientId": "phone", "requestId": "request-1", "originalPrompt": "two cats",
                "parameters": {"model": "model.safetensors", "baseSeed": 1001}}

    async def test_every_route_including_assets_and_socket_requires_auth(self):
        for path in ("/phone-studio/health", "/phone-studio/models", "/phone-studio/v2/jobs/missing",
                     "/phone-studio/v2/assets/missing", "/phone-studio/v2/ws?jobId=missing"):
            reply = await self.client.get(path)
            self.assertEqual(reply.status, 403)
            self.assertEqual((await reply.json())["code"], "authentication_failed")
        reply = await self.client.get("/phone-studio/health", headers={"X-Phone-Studio-Token": "studio-secret"})
        self.assertEqual(reply.status, 401)
        reply = await self.client.get("/phone-studio/health", headers=self.headers)
        health = await reply.json()
        self.assertEqual(health["service"], "phone-studio-router")
        self.assertTrue(health["ok"])
        self.assertNotIn("secret", str(health))

    async def test_submission_full_snapshot_recovery_conflict_and_json_limit(self):
        reply = await self.client.post("/phone-studio/v2/jobs", json=self.body(), headers=self.headers)
        self.assertEqual(reply.status, 202)
        first = await reply.json()
        self.assertIn("jobId", first)
        self.assertNotIn("job", first)
        replay = await self.client.post("/phone-studio/v2/jobs", json=self.body(), headers=self.headers)
        self.assertEqual((await replay.json())["jobId"], first["jobId"])
        lookup = await self.client.get("/phone-studio/v2/requests/request-1?clientId=phone", headers=self.headers)
        self.assertEqual((await lookup.json())["jobId"], first["jobId"])
        missing = await self.client.get("/phone-studio/v2/requests/request-1?clientId=other", headers=self.headers)
        self.assertEqual(missing.status, 404)
        conflict = self.body(); conflict["originalPrompt"] = "three cats"
        result = await self.client.post("/phone-studio/v2/jobs", json=conflict, headers=self.headers)
        self.assertEqual(result.status, 409)
        oversized = await self.client.post("/phone-studio/v2/jobs", data=b"x" * 65537, headers={**self.headers, "Content-Type": "application/json"})
        self.assertEqual(oversized.status, 413)

    async def test_upload_kind_first_is_durable_and_binary_read_is_authenticated(self):
        encoded = io.BytesIO(); Image.new("RGB", (16, 24), "red").save(encoded, format="PNG")
        form = aiohttp.FormData()
        form.add_field("kind", "image")
        form.add_field("file", encoded.getvalue(), filename="phone.jpg", content_type="application/octet-stream")
        reply = await self.client.post("/phone-studio/v2/assets", data=form, headers=self.headers)
        self.assertEqual(reply.status, 201)
        asset = await reply.json()
        self.assertEqual((asset["width"], asset["height"]), (16, 24))
        self.assertTrue((self.config.drive / "assets" / (asset["assetId"] + ".png")).is_file())
        image_reply = await self.client.get("/phone-studio/v2/assets/" + asset["assetId"], headers=self.headers)
        self.assertEqual(image_reply.status, 200)
        self.assertEqual(image_reply.content_type, "image/png")
        self.assertTrue((await image_reply.read()).startswith(b"\x89PNG"))
        denied = await self.client.get("/phone-studio/v2/assets/" + asset["assetId"])
        self.assertEqual(denied.status, 403)

    async def test_socket_sends_revision_and_updates_without_job_payload(self):
        reply = await self.client.post("/phone-studio/v2/jobs", json=self.body(), headers=self.headers)
        job = await reply.json()
        socket = await self.client.ws_connect("/phone-studio/v2/ws?jobId=" + job["jobId"], headers=self.headers)
        try:
            first = await socket.receive_json(timeout=2)
            self.assertEqual(first, {"type": "job", "jobId": job["jobId"], "revision": 1})
            await self.service.set_fields(job["jobId"], state="enhancing")
            second = await socket.receive_json(timeout=2)
            self.assertEqual(second["revision"], 2)
            self.assertEqual(set(second), {"type", "jobId", "revision"})
        finally:
            await socket.close()

    async def test_retry_key_replay_returns_snapshot_and_same_parent_id(self):
        reply = await self.client.post("/phone-studio/v2/jobs", json=self.body(), headers=self.headers)
        job = await reply.json()
        await self.service.set_fields(job["jobId"], state="failed", workers=[{"workerId": "w1", "name": "Worker", "seed": 1001,
            "state": "failed", "requestId": "old", "clientId": "old-client", "promptId": None, "submissionAttempted": False}])
        path = f"/phone-studio/v2/jobs/{job['jobId']}/retry"
        first = await self.client.post(path, json={"requestId": "retry-1"}, headers=self.headers)
        snapshot = await first.json()
        self.assertEqual(snapshot["jobId"], job["jobId"])
        replay = await self.client.post(path, json={"requestId": "retry-1"}, headers=self.headers)
        self.assertEqual(await replay.json(), snapshot)
        unsafe = await self.client.post(path, json={}, headers=self.headers)
        self.assertEqual(unsafe.status, 409)


    async def test_http_status_and_request_routes_restore_pending_durability_and_schedule_saved_id(self):
        with patch.object(self.service.journal, "_backup", side_effect=OSError("Unavailable test Drive")):
            response = await self.client.post("/phone-studio/v2/jobs", json=self.body(), headers=self.headers)
            self.assertEqual(response.status, 500)
            self.assertNotIn("Unavailable test Drive", str(await response.json()))
            saved = self.service.journal.recover("phone", "request-1")
            lookup = await self.client.get("/phone-studio/v2/requests/request-1?clientId=phone", headers=self.headers)
            self.assertEqual(lookup.status, 500)
        scheduled = []
        self.service.schedule = scheduled.append
        with patch.object(self.service.journal, "_backup", wraps=self.service.journal._backup) as backup:
            response = await self.client.get("/phone-studio/v2/requests/request-1?clientId=phone", headers=self.headers)
            self.assertEqual(response.status, 200)
            self.assertEqual(await response.json(), saved)
            status = await self.client.get("/phone-studio/v2/jobs/" + saved["jobId"], headers=self.headers)
            self.assertEqual(status.status, 200)
            self.assertEqual(await status.json(), saved)
            self.assertEqual(scheduled, [saved["jobId"], saved["jobId"]])
            self.assertEqual(backup.call_count, 1)
