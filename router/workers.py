"""Configured-worker transport. Mutating render POSTs are never blindly replayed."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import time
import uuid
from pathlib import Path

import aiohttp

from .config import RouterError, model_name

LOGGER = logging.getLogger("phone-studio-router.workers")


class WorkerFailure(Exception):
    def __init__(self, message, uncertain=False, *, resume_only=False):
        super().__init__(message)
        self.uncertain = uncertain
        # A known accepted render must be followed/copied, never submitted again.
        # This differs from a definite execution failure and unknown acceptance.
        self.resume_only = resume_only


def _runtime_diagnostics(value):
    """Only the small, authenticated baseline fields enter router health."""
    if not isinstance(value, dict):
        return {}
    result = {}
    for name, pattern in (("runtimeId", r"[A-Za-z0-9_.-]{1,128}"),
                          ("buildFingerprint", r"[a-fA-F0-9]{64}"),
                          ("bridgeSha256", r"[a-fA-F0-9]{64}"),
                          ("comfyRevision", r"[a-fA-F0-9]{40}"),
                          ("torch", r"[A-Za-z0-9.+_-]{1,40}"),
                          ("cuda", r"[0-9.]{1,16}")):
        item = value.get(name)
        if isinstance(item, str) and re.fullmatch(pattern, item):
            result[name] = item
    for name in ("compatibilityMode", "comfyCompilerDisabled"):
        if type(value.get(name)) is bool:
            result[name] = value[name]
    for name, allowed in (("attention", {"pytorch", "sage", "sageattention", "t4_native"}),
                          ("stage", {"ready", "server_started"})):
        if isinstance(value.get(name), str) and value[name] in allowed:
            result[name] = value[name]
    options = value.get("effectiveOptions")
    if isinstance(options, dict):
        result["effectiveOptions"] = {key: options[key] for key in (
            "FAST_T4_FLASH_ATTENTION", "FAST_SAGE_ATTENTION", "FAST_DENOISE_CACHE",
            "FAST_CONDITIONING_CACHE", "FAST_FP16_ACCUMULATION", "FAST_FP16_INTERMEDIATES",
            "FAST_FP16_VAE", "AUTO_COMPILE") if type(options.get(key)) is bool}
    memory = value.get("memory")
    if isinstance(memory, dict):
        result["memory"] = {key: memory[key] for key in ("MemAvailableBytes", "SwapFreeBytes",
            "SwapTotalBytes", "VmRSSBytes", "VmHWMBytes", "VmSwapBytes", "gpuFreeBytes", "gpuTotalBytes")
            if type(memory.get(key)) is int and 0 <= memory[key] < 2**63}
    return result


class WorkerClient:
    def __init__(self, config):
        self.config = config
        self.session = None
        self.observed = {}

    async def start(self):
        if self.session is None:
            trace = aiohttp.TraceConfig()
            async def reject_redirect(session, context, parameters):
                raise WorkerFailure("Worker address redirected; update its final tunnel URL.")
            trace.on_request_redirect.append(reject_redirect)
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30), trust_env=False, trace_configs=[trace])

    async def close(self):
        if self.session is not None:
            await self.session.close()
            self.session = None

    def _options(self, worker):
        headers = {"X-Phone-Studio-Token": worker.studio_token, "ngrok-skip-browser-warning": "1"}
        if worker.tunnel_user and worker.tunnel_password:
            headers["Authorization"] = aiohttp.encode_basic_auth(worker.tunnel_user, worker.tunnel_password, encoding="latin1")
        return {"headers": headers, "allow_redirects": False}

    async def json(self, worker, method, path, *, body=None, params=None, data=None, timeout=20):
        await self.start()
        try:
            async with self.session.request(method, worker.server_url + path,
                    json=body, params=params, data=data,
                    timeout=aiohttp.ClientTimeout(total=max(0.1, timeout)), **self._options(worker)) as response:
                raw = bytearray()
                async for chunk in response.content.iter_chunked(16384):
                    raw.extend(chunk)
                    if len(raw) > 2 * 1024**2:
                        raise WorkerFailure("Worker returned an oversized metadata reply.", method == "POST")
                if response.status >= 500 or response.status in (408, 425, 429):
                    raise WorkerFailure("Worker or tunnel is temporarily unavailable.", method == "POST")
                if response.status in (401, 403):
                    raise WorkerFailure("Worker credentials were rejected.")
                if response.status >= 400:
                    # Do not echo upstream HTML, URLs, echoed graphs or secrets.
                    raise WorkerFailure(f"Worker rejected the operation (HTTP {response.status}).")
                if 300 <= response.status < 400:
                    raise WorkerFailure("Worker address redirected; update its final tunnel URL.", method == "POST")
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise ValueError("not an object")
                return value
        except WorkerFailure:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, UnicodeError) as exc:
            raise WorkerFailure("Lost contact with worker or received an unreadable reply.", method == "POST") from exc

    async def probe(self, worker, *, cached=True, timeout=13):
        health, catalog = {}, {}
        async def get_health():
            nonlocal health
            health = await self.json(worker, "GET", "/phone-studio/health", timeout=8)
        async def get_catalog():
            nonlocal catalog
            catalog = await self.json(worker, "GET", "/phone-studio/models",
                                      params={"cached": "1" if cached else "0"}, timeout=12)
        try:
            # The pair is bounded per worker, so a slow third endpoint cannot
            # cancel observations already completed by the first two.
            tasks = [asyncio.create_task(get_health()), asyncio.create_task(get_catalog())]
            try:
                async with asyncio.timeout(timeout):
                    await asyncio.gather(*tasks)
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            if not health.get("ok") or not isinstance(health.get("instanceId"), str):
                raise WorkerFailure("Worker bridge is not ready.")
            checkpoints = [item for item in catalog.get("checkpoints", []) if isinstance(item, str)]
            loras = [item for item in catalog.get("loras", []) if isinstance(item, str)]
            result = {"workerId": worker.worker_id, "name": worker.name, "online": True,
                      "checkpointCount": len(checkpoints), "message": "Ready", "runtimeId": health["instanceId"],
                      "checkpoints": checkpoints, "loras": loras,
                      "capabilities": health.get("capabilities") if isinstance(health.get("capabilities"), dict) else {},
                      "defaultCheckpoint": catalog.get("defaultCheckpoint", ""),
                      "probeStage": "ready", "stale": False}
        except TimeoutError:
            bridge_ready = health.get("ok") is True and isinstance(health.get("instanceId"), str)
            result = {"workerId": worker.worker_id, "name": worker.name, "online": False,
                      "checkpointCount": 0, "message": (
                          "Worker catalog check timed out; authenticated bridge responded."
                          if bridge_ready else "Worker health check timed out."),
                      "runtimeId": health.get("instanceId", "") if bridge_ready else "",
                      "checkpoints": [], "loras": [], "capabilities": {},
                      "probeStage": "catalog_timeout" if bridge_ready else "health_timeout", "stale": False}
        except WorkerFailure as error:
            bridge_ready = (health.get("ok") is True and isinstance(health.get("instanceId"), str)
                            and bool(health["instanceId"]))
            result = {"workerId": worker.worker_id, "name": worker.name, "online": False,
                      "checkpointCount": 0, "message": ("Worker catalog check failed; authenticated bridge responded. " + str(error)
                                                         if bridge_ready else str(error)),
                      "runtimeId": health["instanceId"] if bridge_ready else "", "checkpoints": [], "loras": [], "capabilities": {},
                      "probeStage": "catalog_rejected_or_unreachable" if bridge_ready else "rejected_or_unreachable", "stale": False}
        result["observedAtMillis"] = int(time.time() * 1000)
        result["workerRuntime"] = _runtime_diagnostics(health.get("workerRuntime"))
        self.observed[worker.worker_id] = result
        return result

    async def probes(self, *, cached=True, timeout=13):
        return await asyncio.gather(*(self.probe(worker, cached=cached, timeout=timeout)
                                      for worker in self.config.workers))

    async def upload(self, worker, path: Path, suffix="source"):
        import hashlib
        path = Path(path)
        name = f"router-{hashlib.sha256(path.read_bytes()).hexdigest()}-{suffix}.png"
        with path.open("rb") as file:
            form = aiohttp.FormData()
            form.add_field("image", file, filename=name, content_type="image/png")
            form.add_field("type", "input")
            form.add_field("overwrite", "false")
            reply = await self.json(worker, "POST", "/upload/image", data=form, timeout=60)
        actual = reply.get("name")
        subfolder = reply.get("subfolder", "")
        if not isinstance(actual, str) or "/" in actual or "\\" in actual or not actual:
            raise WorkerFailure("Worker returned an invalid uploaded-image filename.")
        if subfolder:
            model_name(subfolder, "Upload folder")
        return (subfolder + "/" if subfolder else "") + actual

    async def recover(self, worker, client_id, request_id, expected_runtime):
        # An absence reply after a runtime reset is not proof a previous POST was
        # never accepted. Return uncertainty, not permission to render twice.
        try:
            health = await self.json(worker, "GET", "/phone-studio/health", timeout=8)
        except WorkerFailure as exc:
            raise WorkerFailure("Could not verify the earlier render submission.", True) from exc
        if health.get("instanceId") != expected_runtime:
            raise WorkerFailure("Worker restarted while submission was uncertain. Check its notebook before retrying.", True)
        try:
            latest = await self.json(worker, "GET", "/phone-studio/latest-job",
                                     params={"clientId": client_id, "requestId": request_id}, timeout=10)
        except WorkerFailure as exc:
            raise WorkerFailure("Could not verify the earlier render submission.", True) from exc
        if latest.get("requestId") == request_id:
            if latest.get("status") == "error":
                raise WorkerFailure("The earlier worker render failed.")
            prompt_id = latest.get("promptId")
            if isinstance(prompt_id, str) and prompt_id and latest.get("status") in {"pending", "done", "unknown"}:
                return prompt_id
        return None

    async def render(self, worker, record, graph, speed_extras, on_change, deadline):
        prompt_id = record.get("promptId")
        request_id = record["requestId"]
        client_id = record["clientId"]
        runtime_id = record["runtimeId"]
        if not prompt_id and record.get("submissionAttempted"):
            for _ in range(6):
                try:
                    prompt_id = await self.recover(worker, client_id, request_id, runtime_id)
                except WorkerFailure as error:
                    if not error.uncertain:
                        raise
                if prompt_id:
                    break
                await asyncio.sleep(min(2, max(0, deadline - time.monotonic())))
            if not prompt_id:
                raise WorkerFailure("Cannot confirm the earlier render was received; it will not be submitted twice.", True)
        if not prompt_id:
            await on_change({"state": "submitting", "stage": "Submitting", "submissionAttempted": True}, True)
            payload = {"prompt": graph, "client_id": client_id,
                       "extra_data": {"phone_studio_request_id": request_id,
                                      "phone_studio_speed_extras": speed_extras}}
            observed = self.observed.get(worker.worker_id, {})
            if observed.get("capabilities", {}).get("clientPromptId") is True:
                # This UUID is only a correlation aid; stock ComfyUI has no
                # duplicate-submit protection for an existing prompt_id.
                payload["prompt_id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, request_id))
            try:
                reply = await self.json(worker, "POST", "/prompt", body=payload,
                                        timeout=min(60, max(0.1, deadline - time.monotonic())))
                prompt_id = reply.get("prompt_id")
                if not isinstance(prompt_id, str) or not prompt_id:
                    raise WorkerFailure("Worker acceptance reply did not include a prompt ID.", True)
            except WorkerFailure as error:
                if not error.uncertain:
                    raise
                await on_change({"stage": "Checking whether submission arrived"}, False)
                for _ in range(6):
                    try:
                        prompt_id = await self.recover(worker, client_id, request_id, runtime_id)
                    except WorkerFailure as recovery_error:
                        if not recovery_error.uncertain:
                            raise
                    if prompt_id:
                        break
                    await asyncio.sleep(min(2, max(0, deadline - time.monotonic())))
                if not prompt_id:
                    raise WorkerFailure("Render submission is uncertain. No automatic duplicate was sent.", True) from error
        # Also persist an ID recovered from an earlier uncertain submission.
        # Later follow/retrieval failure can then retain its accepted identity.
        try:
            await on_change({"promptId": prompt_id, "state": "queued", "stage": "Queued"}, True)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # POST may already have succeeded. Service will inspect the current
            # durable journal to distinguish saved ID from unknown acceptance.
            raise WorkerFailure("Accepted worker prompt could not be published durably; another render will not be submitted.",
                                True, resume_only=True) from error
        wake = asyncio.Event()
        observer = asyncio.create_task(self._watch(worker, client_id, prompt_id, on_change, wake))
        transient_started = None
        try:
            while time.monotonic() < deadline:
                try:
                    try:
                        history = await self.json(worker, "GET", f"/history/{prompt_id}", timeout=min(20, max(0.1, deadline - time.monotonic())))
                    except WorkerFailure as error:
                        raise WorkerFailure(str(error), resume_only=True) from error
                    entry = history.get(prompt_id, {})
                    if not isinstance(entry, dict):
                        raise WorkerFailure("Worker history reply is invalid.", resume_only=True)
                    status = entry.get("status", {})
                    if (not isinstance(status, dict)
                            or ("completed" in status and type(status["completed"]) is not bool)
                            or ("status_str" in status and not isinstance(status["status_str"], str))):
                        raise WorkerFailure("Worker history status is invalid.", resume_only=True)
                    if isinstance(status, dict) and status.get("status_str") == "error":
                        raise WorkerFailure("Worker reported a generation error. Check that worker notebook.")
                    outputs = entry.get("outputs", {})
                    if not isinstance(outputs, dict) or any(not isinstance(output, dict)
                            or not isinstance(output.get("images", []), list)
                            or any(not isinstance(image, dict) for image in output.get("images", []))
                            for output in outputs.values()):
                        raise WorkerFailure("Worker history output metadata is invalid.", resume_only=True)
                    images = [image for output in outputs.values() if isinstance(output, dict)
                              for image in output.get("images", []) if isinstance(image, dict)] if isinstance(outputs, dict) else []
                    if images:
                        return images
                    if isinstance(status, dict) and status.get("completed"):
                        raise WorkerFailure("Worker finished without an image.")
                    transient_started = None
                except WorkerFailure as error:
                    # Definite execution errors are terminal. Only transport
                    # failures get a short reconnect window.
                    if not str(error).startswith(("Lost contact", "Worker or tunnel")):
                        raise
                    if transient_started is None:
                        transient_started = time.monotonic()
                    if time.monotonic() - transient_started > 90:
                        raise WorkerFailure("Lost contact with the worker; resume its accepted render when reachable.", resume_only=True) from error
                    await on_change({"stage": "Reconnecting"}, False)
                wake.clear()
                try:
                    await asyncio.wait_for(wake.wait(), timeout=min(2, max(0.01, deadline - time.monotonic())))
                except asyncio.TimeoutError:
                    pass
            raise WorkerFailure("Worker deadline expired; resume its accepted render without submitting another.", resume_only=True)
        except asyncio.CancelledError:
            raise
        except WorkerFailure:
            raise
        except Exception as error:
            raise WorkerFailure("Could not follow the accepted worker render; another render will not be submitted.", resume_only=True) from error
        finally:
            observer.cancel()
            try:
                await observer
            except asyncio.CancelledError:
                pass
            except Exception as error:
                # Progress socket is optional; history remains authoritative.
                # Log only type, never echoed payloads, URLs or exception text.
                LOGGER.warning("Accepted worker progress observer failed (%s); history remains authoritative.", type(error).__name__)

    async def _watch(self, worker, client_id, prompt_id, on_change, wake):
        try:
            await self.start()
            options = self._options(worker)
            options.pop("allow_redirects")  # Trace rejects redirects before another request.
            async with self.session.ws_connect(worker.server_url + "/ws", params={"clientId": client_id},
                    heartbeat=20, timeout=aiohttp.ClientWSTimeout(ws_close=10), max_msg_size=256 * 1024, **options) as socket:
                async for message in socket:
                    if message.type != aiohttp.WSMsgType.TEXT:
                        continue
                    try:
                        event = json.loads(message.data)
                        data = event.get("data", {})
                        if data.get("prompt_id") not in (None, prompt_id):
                            continue
                        if event.get("type") == "progress" and type(data.get("value")) is int and type(data.get("max")) is int:
                            total = data["max"]
                            if total > 0:
                                await on_change({"state": "rendering", "stage": "Sampling", "stepsDone": max(0, min(total, data["value"])), "stepsTotal": total}, False)
                        if event.get("type") in {"execution_success", "execution_error", "execution_interrupted"} or (event.get("type") == "executing" and data.get("node") is None):
                            wake.set()
                    except (ValueError, AttributeError, TypeError):
                        continue
        except (aiohttp.ClientError, asyncio.TimeoutError, WorkerFailure):
            wake.set()  # History polling stays authoritative if the socket fails.

    async def collect(self, worker, descriptor, target: Path):
        filename, folder, kind = descriptor.get("filename"), descriptor.get("subfolder", ""), descriptor.get("type", "output")
        if not isinstance(filename, str) or not filename or "/" in filename or "\\" in filename or filename in {".", ".."}:
            raise WorkerFailure("Worker returned an invalid image descriptor.", resume_only=True)
        if folder:
            model_name(folder, "Output folder")
        if kind not in ("output", "temp"):
            raise WorkerFailure("Worker returned an unsupported image location.", resume_only=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        await self.start()
        try:
            async with self.session.get(worker.server_url + "/view", params={"filename": filename, "subfolder": folder, "type": kind},
                    timeout=aiohttp.ClientTimeout(total=90), **self._options(worker)) as response:
                if response.status != 200:
                    raise WorkerFailure("Could not retrieve the finished worker image.", resume_only=True)
                total = 0
                with target.open("wb") as file:
                    async for chunk in response.content.iter_chunked(65536):
                        total += len(chunk)
                        if total > self.config.max_upload_bytes:
                            raise WorkerFailure("Worker image exceeded the router image-size limit.", resume_only=True)
                        file.write(chunk)
            return target
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise WorkerFailure("Lost contact while copying a finished image.", resume_only=True) from exc

    async def cancel(self, worker, record):
        prompt_id = record.get("promptId")
        if not prompt_id:
            return False
        # The new endpoint compares/interrupts atomically. An older worker must
        # never receive a global /interrupt that could stop somebody else's job.
        try:
            result = await self.json(worker, "POST", f"/api/jobs/{prompt_id}/cancel", body={}, timeout=10)
            return result.get("cancelled") is True
        except WorkerFailure:
            try:
                queue = await self.json(worker, "GET", "/queue", timeout=8)
                if any(isinstance(item, list) and len(item) > 1 and item[1] == prompt_id for item in queue.get("queue_pending", [])):
                    await self.json(worker, "POST", "/queue", body={"delete": [prompt_id]}, timeout=8)
                    return True
            except WorkerFailure:
                pass
            return False
