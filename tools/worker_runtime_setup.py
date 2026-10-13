"""Bounded worker bootstrap. Importing this module performs no setup or installs.

The fixed ComfyUI source was inspected for Phone Studio's stock node/bridge
interfaces. GPU/runtime compatibility is pending a real warm-up; this is not a
claim that this revision is known-good on the user's workers.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

COMFY_REPOSITORY = "https://github.com/Comfy-Org/ComfyUI.git"
COMFY_REVISION = "58b176f0c8427b1e3b1e0174ded3a7794641388b"
COMFY_REQUIREMENTS_SHA256 = "6c35de207c68baa2254fb10e25a6a48c2142b6019a6106d2547fc293393340f3"
CHECKOUT_MARKER = ".phone-studio-checkout.json"
EXPERIMENTS = ("FAST_T4_FLASH_ATTENTION", "FAST_SAGE_ATTENTION", "FAST_DENOISE_CACHE",
               "FAST_CONDITIONING_CACHE", "FAST_FP16_ACCUMULATION",
               "FAST_FP16_INTERMEDIATES", "FAST_FP16_VAE", "AUTO_COMPILE")


def effective_options(requested, compatibility_mode=True, capability=(7, 5)):
    """One authoritative requested/effective policy, independent of GPU family."""
    effective = {name: bool(requested.get(name, False)) for name in EXPERIMENTS}
    reasons = {}
    for name, value in effective.items():
        if compatibility_mode:
            effective[name] = False
            if value:
                reasons[name] = "disabled by notebook compatibility mode"
    if tuple(capability) != (7, 5) and effective["FAST_T4_FLASH_ATTENTION"]:
        effective["FAST_T4_FLASH_ATTENTION"] = False
        reasons["FAST_T4_FLASH_ATTENTION"] = "requires SM7.5"
    if capability[0] < 8:
        for name in ("FAST_SAGE_ATTENTION", "AUTO_COMPILE"):
            if effective[name]:
                effective[name] = False
                reasons[name] = "requires compute capability 8.0+"
    return {"compatibilityMode": bool(compatibility_mode), "requested": dict(requested),
            "effective": effective, "reasons": reasons}


def confirm_runtime_health(health, expected_instance, expected_runtime):
    """An open socket alone cannot prove this attempt owns the worker service."""
    if (not isinstance(health, dict) or health.get('ok') is not True
            or health.get('instanceId') != expected_instance
            or not isinstance(health.get('workerRuntime'), dict)
            or health['workerRuntime'].get('runtimeId') != expected_runtime):
        raise RuntimeError('Local worker health does not identify this launched instance; '
                           'preserve the other process and inspect the port/ownership conflict.')
    return health


def atomic_text(path, value):
    """Unique staging also works across instances with coincident process IDs."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(path.name + "." + uuid.uuid4().hex + ".part")
    try:
        staging.write_text(value, encoding="utf-8")
        staging.replace(path)
    finally:
        staging.unlink(missing_ok=True)


@contextmanager
def exclusive_artifact(path, timeout=30):
    """Do not break another instance's lock or delete an unknown stale owner."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    owner = uuid.uuid4().hex
    deadline = time.monotonic() + timeout
    while True:
        try:
            with path.open("x", encoding="utf-8") as out:
                out.write(owner)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise RuntimeError("Another instance owns artifact preparation. Preserve its lock; "
                                   "finish that preparation before retrying only this worker.") from None
            time.sleep(0.25)
    try:
        yield
    finally:
        if path.read_text(encoding="utf-8") == owner:
            path.unlink()


def _credential_values(token, password):
    # Kept self-contained for the standalone embedded bootstrap. These are the
    # same existing Latin1 Basic/header rules as the pairing helper and phone.
    if (not isinstance(token, str) or not token.strip() or len(token) > 512
            or token != token.strip() or any(not 32 <= ord(char) <= 126 for char in token)):
        raise RuntimeError("Private worker token is invalid for the authenticated header; existing credentials were preserved.")
    if (not isinstance(password, str) or not password.strip() or len(password) > 512
            or any(ord(char) < 32 or 127 <= ord(char) <= 159 or ord(char) > 255 for char in password)):
        raise RuntimeError("Private worker password contains characters unsupported by existing Basic authentication; existing credentials were preserved.")
    return token, password


def load_credentials(path, token_secret="", password_secret=""):
    import secrets
    if not isinstance(token_secret, str) or not isinstance(password_secret, str):
        raise RuntimeError("Provided private worker credentials are invalid; existing credentials were preserved.")
    path = Path(path)
    with exclusive_artifact(path.with_name(path.name + ".lock")):
        stored_missing = False
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            stored = None
            stored_missing = True
        except (ValueError, OSError):
            raise RuntimeError("Existing private credential file cannot be read; preserve it "
                               "and inspect it privately before rerunning.") from None
        if not stored_missing:
            if not isinstance(stored, dict):
                raise RuntimeError("Existing private credential file is invalid; it was preserved.")
            _credential_values(stored.get("phone_studio_token"), stored.get("tunnel_password"))
        token, password = _credential_values(
            token_secret or (stored or {}).get("phone_studio_token") or secrets.token_urlsafe(32),
            password_secret or (stored or {}).get("tunnel_password") or secrets.token_urlsafe(24))
        # A worker's Secret overrides affect that worker only. Never rewrite a
        # shared existing credential file with a different instance's values.
        if not path.exists():
            atomic_text(path, json.dumps({"phone_studio_token": token,
                                        "tunnel_password": password}, indent=2))
        return token, password


def _redact(text):
    text = re.sub(r"https?://\S+", "[url]", text)
    text = re.sub(r"(?i)(token|password|authorization|api[_-]?key)(\s*[:=]\s*)\S+",
                  r"\1\2[redacted]", text)
    return text[-16000:]


def run_stage(command, *, stage="runtime_setup", log_root=None, timeout=180, **kwargs):
    """Finite command deadlines; retain bounded diagnostics without command/env dumps."""
    log_root = Path(log_root or "/content/phone_studio_worker_diagnostics")
    log_root.mkdir(parents=True, exist_ok=True)
    log = log_root / (stage + "." + uuid.uuid4().hex + ".log")
    print("Worker stage:", stage, "| deadline", timeout, "seconds")
    started = time.monotonic()
    try:
        result = subprocess.run(command, timeout=timeout, capture_output=True, text=True,
                                check=False, **kwargs)
    except subprocess.TimeoutExpired as error:
        atomic_text(log, json.dumps({"stage": stage, "category": "deadline", "timeout": timeout})
                    + "\n" + _redact(str(error.stdout or ""))
                    + "\n" + _redact(str(error.stderr or "")))
        raise RuntimeError(f"Worker {stage} deadline exceeded; see {log}") from None
    atomic_text(log, json.dumps({"stage": stage, "returncode": result.returncode,
                                "elapsedSeconds": round(time.monotonic() - started, 2)})
                + "\n" + _redact(result.stdout or "") + "\n" + _redact(result.stderr or ""))
    if result.returncode:
        raise RuntimeError(f"Worker {stage} failed (exit {result.returncode}); see {log}")
    return result.stdout.strip()


def _protected_package(name):
    name = name.lower().replace("_", "-")
    return name in {"torch", "torchvision", "torchaudio", "triton"} or name.startswith("nvidia-")


def torch_stack(log_root=None):
    code = """import importlib.metadata as m, json, torch
p={d.metadata['Name'].lower().replace('_','-'):d.version for d in m.distributions()}
protected={n:v for n,v in p.items() if n in {'torch','torchvision','torchaudio','triton'} or n.startswith('nvidia-')}
print(json.dumps({'packages':protected,'torchCuda':torch.version.cuda,'cudaAvailable':torch.cuda.is_available()}))
"""
    snapshot = json.loads(run_stage([sys.executable, "-c", code], stage="torch_identity",
                                   log_root=log_root, timeout=45))
    if not {"torch", "torchvision"} <= set(snapshot["packages"]) or not snapshot["torchCuda"]:
        raise RuntimeError("Worker requires an existing matched CUDA Torch/torchvision stack; "
                           "it will not install or replace that stack automatically.")
    return snapshot


def validate_dependency_report(report, stack):
    for item in report.get("install", []):
        name = str(item.get("metadata", {}).get("name", ""))
        if _protected_package(name):
            raise RuntimeError("Dependency preflight would replace/install protected GPU package "
                               + name + "; preserve the current Torch/CUDA stack.")


def prepare_checkout(root, *, log_root=None):
    root = Path(root)
    root.parent.mkdir(parents=True, exist_ok=True)
    marker = root / CHECKOUT_MARKER
    if root.is_symlink():
        raise RuntimeError("ComfyUI checkout is a symlink; preserve it and use a clean local path.")
    if root.exists():
        if not (root / ".git").is_dir():
            raise RuntimeError("Unknown existing ComfyUI directory preserved; use a clean runtime-local path.")
        revision = run_stage(["git", "-C", str(root), "rev-parse", "HEAD"],
                             stage="checkout_identity", log_root=log_root, timeout=30)
        remote = run_stage(["git", "-C", str(root), "remote", "get-url", "origin"],
                           stage="checkout_origin", log_root=log_root, timeout=30)
        changes = run_stage(["git", "-C", str(root), "diff", "--name-only", "HEAD"],
                            stage="checkout_changes", log_root=log_root, timeout=30).splitlines()
        unknown = run_stage(["git", "-C", str(root), "ls-files", "--others", "--exclude-standard"],
                            stage="checkout_untracked", log_root=log_root, timeout=30).splitlines()
        owned = {}
        if marker.is_file():
            try:
                owned = json.loads(marker.read_text(encoding="utf-8"))
            except ValueError:
                pass
        linked = owned.get("links", {}) if owned.get("revision") == COMFY_REVISION else {}
        allowed = {name for name, target in linked.items()
                   if (root / name).is_symlink() and (root / name).resolve() == Path(target).resolve()}
        bad = [p for p in changes if p.split("/", 1)[0] not in allowed]
        unknown = [p for p in unknown if p != CHECKOUT_MARKER and p not in allowed
                   and not p.startswith(".phone-studio-preserved/")]
        if revision != COMFY_REVISION or remote.rstrip("/").removesuffix(".git") != COMFY_REPOSITORY.removesuffix(".git") or bad or unknown:
            raise RuntimeError("Existing ComfyUI revision/source conflicts with this fixed notebook. "
                               "Checkout preserved; capture its package versions and use a clean "
                               "runtime-local path for this notebook. No pull/reset was performed.")
    else:
        staging = root.with_name(root.name + ".phone-studio-" + uuid.uuid4().hex)
        staging.mkdir()
        try:
            for stage, command in (
                ("checkout_init", ["git", "init", str(staging)]),
                ("checkout_remote", ["git", "-C", str(staging), "remote", "add", "origin", COMFY_REPOSITORY]),
                ("checkout_fetch", ["git", "-C", str(staging), "fetch", "--depth", "1", "origin", COMFY_REVISION]),
                ("checkout_pin", ["git", "-C", str(staging), "checkout", "--detach", COMFY_REVISION]),
            ):
                run_stage(command, stage=stage, log_root=log_root, timeout=180)
            atomic_text(staging / CHECKOUT_MARKER, json.dumps({"revision": COMFY_REVISION,
                                                            "repository": COMFY_REPOSITORY, "links": {}}))
            staging.rename(root)
        finally:
            if staging.exists():
                # This invocation created this exact sibling, never an unknown checkout.
                shutil.rmtree(staging)
    if hashlib.sha256((root / "requirements.txt").read_bytes()).hexdigest() != COMFY_REQUIREMENTS_SHA256:
        raise RuntimeError("Pinned ComfyUI requirements checksum differs; checkout was preserved.")
    if not marker.exists():
        atomic_text(marker, json.dumps({"revision": COMFY_REVISION,
                                      "repository": COMFY_REPOSITORY, "links": {}}))
    return COMFY_REVISION


def link_persistent(root, name, target, *, log_root=None):
    """Preserve shipped stock folders; never erase unknown runtime assets."""
    root, target = Path(root), Path(target)
    link = root / name
    target.mkdir(parents=True, exist_ok=True)
    if link.is_symlink():
        if link.resolve() != target.resolve():
            raise RuntimeError(f"Existing {name} link points elsewhere; it was preserved.")
    elif link.exists():
        tracked = set(run_stage(["git", "-C", str(root), "ls-files", "--", name],
                                stage="stock_" + name, log_root=log_root, timeout=30).splitlines())
        files = {p.relative_to(root).as_posix() for p in link.rglob("*") if p.is_file() or p.is_symlink()}
        if not link.is_dir() or files - tracked:
            raise RuntimeError(f"Existing {name} contains unknown files; preserved. "
                               "Move needed assets deliberately or use a clean runtime-local checkout.")
        saved = root / ".phone-studio-preserved"
        saved.mkdir(exist_ok=True)
        link.rename(saved / (name + "." + uuid.uuid4().hex))
        link.symlink_to(target, target_is_directory=True)
    else:
        link.symlink_to(target, target_is_directory=True)
    marker = root / CHECKOUT_MARKER
    record = json.loads(marker.read_text(encoding="utf-8"))
    record.setdefault("links", {})[name] = str(target.resolve())
    atomic_text(marker, json.dumps(record, indent=2))


def install_dependencies(root, *, log_root=None):
    root = Path(root)
    log_root = Path(log_root or "/content/phone_studio_worker_diagnostics")
    log_root.mkdir(parents=True, exist_ok=True)
    before = torch_stack(log_root)
    constraints = log_root / "existing-gpu-stack.txt"
    atomic_text(constraints, "\n".join(f"{n}=={v}" for n, v in sorted(before["packages"].items())) + "\n")
    report_path = log_root / "dependency-preflight.json"
    command = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-input",
               "--only-binary=:all:", "-c", str(constraints), "-r", str(root / "requirements.txt"),
               "pyngrok", "requests"]
    run_stage(command + ["--dry-run", "--report", str(report_path)],
              stage="dependency_preflight", log_root=log_root, timeout=300)
    validate_dependency_report(json.loads(report_path.read_text(encoding="utf-8")), before)
    run_stage(command, stage="dependency_install", log_root=log_root, timeout=600)
    if torch_stack(log_root) != before:
        raise RuntimeError("GPU stack identity changed unexpectedly; stop this worker and inspect private logs.")
    # Check the required startup imports, avoiding unrelated pre-existing Colab
    # package conflicts from a global pip-check policy.
    run_stage([sys.executable, "-c", "import torch, torchvision, aiohttp, numpy, requests, pyngrok"],
              stage="dependency_imports", log_root=log_root, timeout=45)
    return before


def local_custom_nodes(persistent_root, local_root, known_bridge_hashes=()):
    """Keep user nodes, but publish Phone Studio's bridge on instance-local disk."""
    persistent_root, local_root = Path(persistent_root), Path(local_root)
    local_root.mkdir(parents=True, exist_ok=True)
    inventory = []
    for item in sorted(persistent_root.iterdir()):
        if item.name == "phone_studio_bridge":
            source = item / "__init__.py"
            if source.exists() and hashlib.sha256(source.read_bytes()).hexdigest() not in known_bridge_hashes:
                raise RuntimeError("Persistent Phone Studio bridge has unknown/manual changes; "
                                   "preserved. Review those changes before replacing this worker bridge.")
            continue
        inventory.append(item.name)
        link = local_root / item.name
        if link.is_symlink() and link.resolve() == item.resolve():
            continue
        if link.exists() or link.is_symlink():
            raise RuntimeError("Local custom-node path conflicts; preserve it before retrying this worker.")
        link.symlink_to(item, target_is_directory=item.is_dir())
    return inventory
