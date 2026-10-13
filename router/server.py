"""Authenticated aiohttp entry point: ``python -m router.server``."""
from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
import uuid

from aiohttp import web, BasicAuth, WSMsgType

from .config import Config, RouterError, identifier
from .service import RouterService

LOGGER = logging.getLogger("phone-studio-router")
JSON_LIMIT = 64 * 1024
SERVICE_KEY = web.AppKey("service", RouterService)


async def read_json(request, *, empty=False):
    if request.content_type != "application/json":
        if empty and request.content_length in (None, 0):
            return {}
        raise RouterError("Send an application/json request.")
    raw = bytearray()
    async for chunk in request.content.iter_chunked(8192):
        raw.extend(chunk)
        if len(raw) > JSON_LIMIT:
            raise RouterError("The JSON request exceeds 64 KiB.", 413, "request_too_large")
    if empty and not raw:
        return {}
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise RouterError("This request is not valid JSON.") from exc
    if not isinstance(result, dict):
        raise RouterError("Send a JSON object.")
    return result


def create_app(config: Config, service=None):
    service = service or RouterService(config)

    @web.middleware
    async def errors(request, handler):
        try:
            response = await handler(request)
        except RouterError as error:
            response = web.json_response({"error": str(error), "code": error.code}, status=error.status)
        except web.HTTPException as error:
            response = web.json_response({"error": "That router route is unavailable." if error.status == 404 else "Router request was rejected.",
                                         "code": f"http_{error.status}"}, status=error.status)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # Deliberately avoid exception text/traceback: a proxy exception can
            # contain a credential-bearing URL or an echoed upstream payload.
            LOGGER.error("Router handler failed (%s)", type(error).__name__)
            response = web.json_response({"error": "Router could not complete this operation. Check its notebook log.", "code": "router_error"}, status=500)
        if not response.prepared:
            response.headers["Cache-Control"] = "private, no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @web.middleware
    async def authenticate(request, handler):
        token = request.headers.get("X-Phone-Studio-Token", "")
        if len(token) > 1024 or not hmac.compare_digest(token.encode("utf-8"), config.token.encode("utf-8")):
            raise RouterError("Studio token was rejected. Check the router connection.", 403, "authentication_failed")
        if config.basic_user or config.basic_password:
            try:
                auth = BasicAuth.decode(request.headers.get("Authorization", ""))
                valid = hmac.compare_digest(auth.login.encode(), config.basic_user.encode()) and hmac.compare_digest(auth.password.encode(), config.basic_password.encode())
            except (ValueError, UnicodeError):
                valid = False
            if not valid:
                raise RouterError("Tunnel credentials were rejected.", 401, "authentication_failed")
        return await handler(request)

    app = web.Application(middlewares=[errors, authenticate], client_max_size=config.max_upload_bytes + 64 * 1024)
    app[SERVICE_KEY] = service

    async def lifecycle(application):
        await service.start()
        yield
        await service.close()
    app.cleanup_ctx.append(lifecycle)

    routes = web.RouteTableDef()

    @routes.get("/phone-studio/health")
    async def health(request):
        return web.json_response(await service.health())

    @routes.get("/phone-studio/models")
    async def models(request):
        return web.json_response(await service.catalog(cached=request.query.get("cached") == "1"))

    @routes.post("/phone-studio/v2/jobs")
    async def submit(request):
        return web.json_response(await service.submit(await read_json(request)), status=202)

    @routes.get("/phone-studio/v2/jobs/{jobId}")
    async def job(request):
        return web.json_response(await service.get(request.match_info["jobId"]))

    @routes.get("/phone-studio/v2/requests/{requestId}")
    async def recovery(request):
        client = identifier(request.query.get("clientId"), "Client ID")
        request_id = identifier(request.match_info["requestId"], "Request ID")
        return web.json_response(await asyncio.to_thread(service.journal.recover, client, request_id))

    @routes.post("/phone-studio/v2/jobs/{jobId}/cancel")
    async def cancel(request):
        await read_json(request, empty=True)
        return web.json_response(await service.cancel(request.match_info["jobId"]))

    @routes.post("/phone-studio/v2/jobs/{jobId}/retry")
    async def retry(request):
        body = await read_json(request, empty=True)
        if set(body) - {"requestId"}:
            raise RouterError("Retry accepts only an optional requestId.")
        return web.json_response(await service.retry(request.match_info["jobId"], body.get("requestId")))

    @routes.post("/phone-studio/v2/assets")
    async def upload(request):
        if request.content_type != "multipart/form-data":
            raise RouterError("Upload a multipart raster image.")
        reader = await request.multipart()
        scratch = config.root / "uploads"
        scratch.mkdir(parents=True, exist_ok=True)
        path = scratch / f"{uuid.uuid4()}.part"
        kind, file_seen, count, fields = "image", False, 0, 0
        try:
            async for part in reader:
                fields += 1
                if fields > 2:
                    raise RouterError("Upload one file and an optional image/mask kind.")
                if part.name == "kind":
                    raw = await part.read_chunk(8192)
                    if not part.at_eof() or len(raw) > 16:
                        raise RouterError("Invalid image kind.")
                    kind = raw.decode("utf-8")
                elif part.name == "file" and not file_seen:
                    file_seen = True
                    with path.open("wb") as output:
                        while chunk := await part.read_chunk(65536):
                            count += len(chunk)
                            if count > config.max_upload_bytes:
                                raise RouterError("The image upload exceeds 24 MiB.", 413, "asset_too_large")
                            output.write(chunk)
                else:
                    raise RouterError("Upload one file and an optional image/mask kind.")
            if not file_seen or not count:
                raise RouterError("Choose an image to upload.")
            result = await asyncio.to_thread(service.assets.ingest, path, kind)
            return web.json_response(result, status=201)
        finally:
            path.unlink(missing_ok=True)

    @routes.get("/phone-studio/v2/assets/{assetId}")
    async def asset(request):
        asset_id = identifier(request.match_info["assetId"], "Asset ID")
        path = await asyncio.to_thread(service.assets.path, asset_id)
        return web.FileResponse(path, headers={"Content-Type": "image/png", "Content-Disposition": f'inline; filename="{asset_id}.png"'})

    @routes.get("/phone-studio/v2/ws")
    async def websocket(request):
        job_id = identifier(request.query.get("jobId"), "Job ID")
        await service.get(job_id)
        try:
            revision = int(request.query.get("afterRevision", "0"))
            if revision < 0:
                raise ValueError()
        except ValueError as exc:
            raise RouterError("afterRevision must be non-negative.") from exc
        socket = web.WebSocketResponse(heartbeat=20, max_msg_size=1024)
        socket.headers["Cache-Control"] = "private, no-store"
        await socket.prepare(request)
        signal = asyncio.Event()
        service.listeners.setdefault(job_id, set()).add(signal)
        async def receiver():
            async for message in socket:
                if message.type in {WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR}:
                    break
                if message.type in {WSMsgType.TEXT, WSMsgType.BINARY}:
                    # Subscription is read-only; the router executes no socket commands.
                    await socket.close(code=1008, message=b"Read-only subscription")
                    break
        closed = asyncio.create_task(receiver())
        first = True
        try:
            while not socket.closed and not closed.done():
                signal.clear()
                current = await service.get(job_id)
                if first or current["revision"] > revision:
                    first = False
                    revision = current["revision"]
                    await socket.send_json({"type": "job", "jobId": job_id, "revision": revision})
                waiter = asyncio.create_task(signal.wait())
                try:
                    await asyncio.wait((waiter, closed), return_when=asyncio.FIRST_COMPLETED, timeout=30)
                finally:
                    waiter.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await waiter
        finally:
            closed.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await closed
            service.listeners[job_id].discard(signal)
            if not service.listeners[job_id]:
                service.listeners.pop(job_id, None)
        return socket

    @routes.post("/phone-studio/download-model")
    async def download(request):
        return web.json_response(await service.begin_download(await read_json(request)), status=202)

    @routes.get("/phone-studio/downloads/{downloadId}")
    async def download_status(request):
        return web.json_response(await service.download_status(request.match_info["downloadId"]))

    app.add_routes(routes)
    return app


def main():
    logging.basicConfig(level=logging.INFO, format="[phone-studio-router] %(message)s")
    config = Config.from_env()
    # Access logs contain user input/asset IDs and are not needed for normal operation.
    web.run_app(create_app(config), host=config.host, port=config.port, access_log=None)


if __name__ == "__main__":
    main()
