"""Configuration and public-request validation. Secrets never enter snapshots."""
from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from .model_profile import MODEL_REPO, MODEL_REVISION


class RouterError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = "invalid_request"):
        super().__init__(message)
        self.status, self.code = status, code


def identifier(value, label="ID") -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise RouterError(f"{label} must be a short identifier, without paths or spaces.")
    return value


def model_name(value, label="Model") -> str:
    if not isinstance(value, str) or len(value) > 240 or "\\" in value or ":" in value or "\x00" in value:
        raise RouterError(f"{label} filename is invalid.")
    parts = value.split("/")
    if value.startswith("/") or any(part in ("", ".", "..") for part in parts):
        raise RouterError(f"{label} must be a relative catalog filename.")
    return value


def _text(value, label, limit=8000, required=False):
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise RouterError(f"{label} must be text of at most {limit} characters.")
    if required and not value.strip():
        raise RouterError(f"Add {label.lower()}.")
    return value


def _basic_credential(value, label, limit, *, username=False):
    value = _text(value, label, limit)
    # Empty Basic fields are supported for existing token-only private workers.
    # Nonempty fields must retain exactly the bytes used by the Latin1 clients.
    if value and (not value.strip() or any(ord(char) < 32 or 127 <= ord(char) <= 159 or ord(char) > 255 for char in value)):
        raise RouterError(f"{label} contains characters unsupported by existing Basic authentication.")
    if username and (":" in value or value != value.strip()):
        raise RouterError(f"{label} must be a clean username without a colon.")
    return value


def _studio_token(value, label):
    value = _text(value, label, 512, required=True)
    if value != value.strip() or any(not 32 <= ord(char) <= 126 for char in value):
        raise RouterError(f"{label} must use visible ASCII text without outer whitespace for its authenticated header.")
    return value


def _number(value, label, low, high):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not low <= value <= high:
        raise RouterError(f"{label} must be between {low} and {high}.")
    return value


def _boolean(value, label):
    if type(value) is not bool:
        raise RouterError(f"{label} must be true or false.")
    return value


def validate_request(body: dict) -> dict:
    if not isinstance(body, dict):
        raise RouterError("Send a JSON object.")
    allowed = {"schemaVersion", "clientId", "requestId", "operation", "originalPrompt", "negativePrompt", "parameters", "options", "sourceAssetId", "maskAssetId", "editInstruction", "preservation"}
    if set(body) - allowed:
        raise RouterError("Unknown request fields. Graphs, source URLs and worker addresses are not accepted.")
    if type(body.get("schemaVersion")) is not int or body["schemaVersion"] != 2:
        raise RouterError("This router needs schemaVersion 2.")
    operation = body.get("operation", "generate")
    if operation not in ("generate", "edit"):
        raise RouterError("Operation must be generate or edit.")
    params = body.get("parameters", {})
    options = body.get("options", {})
    if not isinstance(params, dict) or not isinstance(options, dict):
        raise RouterError("Parameters and options must be objects.")
    if set(params) - {"model", "lora", "loraStrength", "width", "height", "preset", "baseSeed", "varySeedPerWorker", "speedExtras"}:
        raise RouterError("Unknown generation parameters.")
    if set(options) - {"enhancePrompt", "reviewCandidates", "auxiliaryInpaint"}:
        raise RouterError("Unknown job options.")
    width, height = params.get("width", 768), params.get("height", 1024)
    if type(width) is not int or type(height) is not int or (width, height) not in ((768, 1024), (1024, 1024), (1024, 768)):
        raise RouterError("Choose the tall, square or wide working canvas.")
    seed = params.get("baseSeed")
    if type(seed) is not int or not 0 <= seed <= 9223372036854775807:
        raise RouterError("baseSeed must be a resolved non-negative 64-bit seed.")
    preset = params.get("preset", "balanced")
    if preset not in ("balanced", "fast"):
        raise RouterError("Preset must be balanced or fast.")
    lora = params.get("lora", "")
    if lora:
        model_name(lora, "LoRA")
    result = {
        "schemaVersion": 2, "clientId": identifier(body.get("clientId"), "Client ID"),
        "requestId": identifier(body.get("requestId"), "Request ID"), "operation": operation,
        "originalPrompt": _text(body.get("originalPrompt", ""), "Original prompt", required=operation == "generate"),
        "negativePrompt": _text(body.get("negativePrompt", ""), "Negative prompt"),
        "parameters": {"model": model_name(params.get("model")), "lora": lora,
            "loraStrength": float(_number(params.get("loraStrength", 0.8), "LoRA strength", -2, 2)),
            "width": width, "height": height, "preset": preset, "baseSeed": seed,
            "varySeedPerWorker": _boolean(params.get("varySeedPerWorker", True), "Seed variation"),
            "speedExtras": _boolean(params.get("speedExtras", True), "Acceleration")},
        "options": {"enhancePrompt": _boolean(options.get("enhancePrompt", True), "Prompt enhancement"),
                    "reviewCandidates": _boolean(options.get("reviewCandidates", True), "Candidate review"),
                    "auxiliaryInpaint": _boolean(options.get("auxiliaryInpaint", True), "Stronger inpainting")},
        "sourceAssetId": None, "maskAssetId": None, "editInstruction": None,
        "preservation": float(_number(body.get("preservation", 0.65), "Preservation", 0, 1)),
    }
    if operation == "edit":
        result["sourceAssetId"] = identifier(body.get("sourceAssetId"), "Source asset ID")
        result["editInstruction"] = _text(body.get("editInstruction"), "Edit instruction", required=True)
        if body.get("maskAssetId") is not None:
            result["maskAssetId"] = identifier(body["maskAssetId"], "Mask asset ID")
    elif any(body.get(key) is not None for key in ("sourceAssetId", "maskAssetId", "editInstruction")):
        raise RouterError("Image assets and edit instructions belong to edit jobs.")
    return result


@dataclass(frozen=True)
class WorkerConfig:
    worker_id: str
    name: str
    server_url: str
    tunnel_user: str = "studio"
    tunnel_password: str = field(default="", repr=False)
    studio_token: str = field(default="", repr=False)

    @classmethod
    def from_dict(cls, body):
        if not isinstance(body, dict):
            raise RouterError("Each configured worker must be an object.")
        url = body.get("serverUrl", "").rstrip("/")
        parsed = urlsplit(url)
        # Loopback HTTP is useful for a permitted local runtime and mocked tests.
        local = parsed.hostname in ("127.0.0.1", "localhost", "::1")
        if parsed.scheme not in ("https", "http") or (parsed.scheme == "http" and not local) or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise RouterError("Configured workers need a final HTTPS address (HTTP only on loopback).")
        return cls(identifier(body.get("workerId"), "Worker ID"),
                   _text(body.get("name", body["workerId"]), "Worker name", 80, True), url,
                   _basic_credential(body.get("tunnelUser", "studio"), "Tunnel user", 128, username=True),
                   _basic_credential(body.get("tunnelPassword", ""), "Tunnel password", 512),
                   _studio_token(body.get("studioToken", ""), "Worker token"))


@dataclass
class Config:
    root: Path
    drive: Path
    token: str = field(repr=False)
    workers: tuple[WorkerConfig, ...] = ()
    llm_url: str = "http://127.0.0.1:8081"
    llm_api_key: str = field(default="", repr=False)
    llm_model: str = MODEL_REPO
    llm_revision: str = MODEL_REVISION
    host: str = "127.0.0.1"
    port: int = 8080
    basic_user: str = ""
    basic_password: str = field(default="", repr=False)
    asset_quota_bytes: int = 2 * 1024**3
    max_upload_bytes: int = 24 * 1024**2
    max_image_pixels: int = 16 * 1024**2
    disk_reserve_bytes: int = 512 * 1024**2
    job_timeout_seconds: int = 900
    worker_timeout_seconds: int = 720
    max_queued_jobs: int = 8

    @classmethod
    def from_env(cls):
        workers = json.loads(os.environ.get("PHONE_STUDIO_WORKERS_JSON", "[]"))
        if not isinstance(workers, list) or not 1 <= len(workers) <= 3:
            raise RouterError("Configure one to three workers in PHONE_STUDIO_WORKERS_JSON.")
        configs = tuple(WorkerConfig.from_dict(item) for item in workers)
        if len({item.worker_id for item in configs}) != len(configs):
            raise RouterError("Configured worker IDs must be unique.")
        token = _studio_token(os.environ.get("PHONE_STUDIO_TOKEN", ""), "Router token")
        basic_user = _basic_credential(os.environ.get("PHONE_STUDIO_ROUTER_USER", ""), "Router tunnel user", 128, username=True)
        basic_password = _basic_credential(os.environ.get("PHONE_STUDIO_ROUTER_PASSWORD", ""), "Router tunnel password", 512)
        return cls(root=Path(os.environ.get("PHONE_STUDIO_ROUTER_ROOT", "/content/phone-studio-router")),
            drive=Path(os.environ.get("PHONE_STUDIO_ROUTER_DRIVE", "/content/drive/MyDrive/PhoneStudioRouter")),
            token=token, workers=configs,
            llm_url=os.environ.get("PHONE_STUDIO_LLM_URL", "http://127.0.0.1:8081"),
            llm_api_key=os.environ.get("PHONE_STUDIO_LLM_API_KEY", ""),
            llm_model=os.environ.get("PHONE_STUDIO_LLM_MODEL", cls.llm_model),
            llm_revision=os.environ.get("PHONE_STUDIO_LLM_REVISION", cls.llm_revision),
            host=os.environ.get("PHONE_STUDIO_ROUTER_HOST", "127.0.0.1"),
            port=int(os.environ.get("PHONE_STUDIO_ROUTER_PORT", "8080")),
            basic_user=basic_user,
            basic_password=basic_password,
            asset_quota_bytes=int(os.environ.get("PHONE_STUDIO_ROUTER_ASSET_MAX_MB", "2048")) * 1024**2)

