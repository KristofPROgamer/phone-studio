"""CPU/loopback checks for independent health and explicit inventory refresh."""
import asyncio
import tempfile
import unittest
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from router.config import Config, WorkerConfig
from router.server import create_app
from router.service import RouterService
from router.workers import WorkerClient


class ReadyLLM:
    async def health(self):
        await asyncio.sleep(0.01)
        return {"ready": True, "model": "synthetic", "revision": "fixture",
                "degraded": False, "message": "Ready"}

    async def close(self):
        pass


class HealthAndCatalogTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.config = Config(root / "local", root / "drive", "private",
            workers=tuple(WorkerConfig(f"w{i}", f"Worker {i}", "https://fixture.invalid",
                                      studio_token="private-worker") for i in (1, 2, 3)),
            disk_reserve_bytes=0)
        self.workers = WorkerClient(self.config)
        self.service = RouterService(self.config, workers=self.workers, llm=ReadyLLM())
        self.closed = False

    async def asyncTearDown(self):
        if not self.closed:
            await self.service.close()
        self.temp.cleanup()

    async def test_slow_third_catalog_keeps_completed_workers_and_llm(self):
        cancelled = []
        async def json_reply(worker, method, path, **kwargs):
            if path.endswith("models") and worker.worker_id == "w3":
                try:
                    await asyncio.sleep(30)
                finally:
                    cancelled.append(worker.worker_id)
            await asyncio.sleep(0.01)
            if path.endswith("health"):
                return {"ok": True, "instanceId": "runtime-" + worker.worker_id,
                    "workerRuntime": {"comfyRevision": "a" * 40, "compatibilityMode": True,
                        "memory": {"gpuFreeBytes": 2048, "credential": "private-secret"},
                        "attention": "pytorch", "stage": "ready", "secret": "private-secret"}}
            return {"checkpoints": ["existing.safetensors"], "loras": []}
        self.workers.json = json_reply
        result = await self.service.health()
        self.assertTrue(result["llm"]["ready"])
        self.assertFalse(result["llm"]["stale"])
        self.assertEqual([w["online"] for w in result["workers"]], [True, True, False])
        self.assertEqual(result["workers"][2]["probeStage"], "catalog_timeout")
        self.assertEqual(result["workers"][2]["runtimeId"], "runtime-w3")
        self.assertEqual(cancelled, ["w3"])
        self.assertEqual(result["workers"][2]["workerRuntime"]["attention"], "pytorch")
        self.assertNotIn("private-secret", str(result))

    async def test_fresh_phone_catalog_bypasses_worker_cache_immediately(self):
        files = ["old.safetensors"]
        cache = list(files)
        intents = []
        async def reply(worker, method, path, **kwargs):
            nonlocal cache
            if path.endswith("health"):
                return {"ok": True, "instanceId": "runtime-" + worker.worker_id}
            intent = kwargs["params"]["cached"]
            intents.append(intent)
            if intent == "0":
                cache = list(files)
            return {"checkpoints": cache, "loras": []}
        self.workers.json = reply
        await self.workers.probes()
        files.append("added.safetensors")
        routine = await self.workers.probes()
        self.assertNotIn("added.safetensors", routine[0]["checkpoints"])
        client = TestClient(TestServer(create_app(self.config, self.service)))
        await client.start_server()
        try:
            response = await client.get("/phone-studio/models", headers={"X-Phone-Studio-Token": "private"})
            self.assertEqual(response.status, 200)
            self.assertIn("added.safetensors", (await response.json())["checkpoints"])
            self.assertEqual(intents, ["1"] * 6 + ["0"] * 3)
            await client.get("/phone-studio/models?cached=1", headers={"X-Phone-Studio-Token": "private"})
            self.assertEqual(intents[-3:], ["1"] * 3)
        finally:
            await client.close()
            self.closed = True
