"""Optional pinned Fooocus auxiliary setup, invoked by the worker notebook.

Importing this helper installs/runs nothing. No Torch/CUDA dependency is replaced.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

FOOOCUS_SOURCE_REVISION = "bd6d8fd5104d539187dfb172d07352215c09fcaa"
FOOOCUS_WEIGHTS_REVISION = "74bbcc070e55219adb9b6c3b0d035b34e3697d1d"
FOOOCUS_WEIGHTS = {
    "fooocus_inpaint_head.pth": (52602, "32f7f838e0c6d8f13437ba8411e77a4688d77a2e34df8857e4ef4d51f6b97692"),
    "inpaint_v26.fooocus.patch": (1323362033, "f8657a025104e22d70f9c060635d8e8c2196f433871a2f68dc40abd2171f0d59"),
}


def _hash_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _download_weight(name: str, root: Path, reserve_gb: float) -> None:
    size, digest = FOOOCUS_WEIGHTS[name]
    path = root / name
    if path.is_file() and path.stat().st_size == size and _hash_file(path) == digest:
        return
    if path.exists():
        raise RuntimeError(f"Existing {name} does not match the pinned publisher file; move it aside before enabling Fooocus.")
    if shutil.disk_usage(root).free < size + reserve_gb * 1024**3:
        raise RuntimeError("Not enough free space for the Fooocus auxiliary weights and the configured disk reserve.")
    url = f"https://huggingface.co/lllyasviel/fooocus_inpaint/resolve/{FOOOCUS_WEIGHTS_REVISION}/{name}"
    temporary = root / (name + "." + uuid.uuid4().hex + ".part")
    started = time.monotonic()
    hasher, downloaded = hashlib.sha256(), 0
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "PhoneStudio-edit-worker"})
        with urllib.request.urlopen(request, timeout=45) as response, temporary.open("xb") as handle:
            while block := response.read(4 * 1024 * 1024):
                downloaded += len(block)
                if downloaded > size or time.monotonic() - started > 600:
                    raise RuntimeError("Fooocus download exceeded its expected size/time limit.")
                hasher.update(block)
                handle.write(block)
        if downloaded != size or hasher.hexdigest() != digest:
            raise RuntimeError("Fooocus publisher-file integrity check failed.")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _install_source(custom_nodes_root: Path) -> Path:
    target = custom_nodes_root / "phone_studio_fooocus_inpaint"
    if target.exists():
        try:
            revision = subprocess.check_output(["git", "-C", str(target), "rev-parse", "HEAD"], text=True, timeout=15).strip()
            changes = subprocess.check_output(["git", "-C", str(target), "status", "--porcelain", "--untracked-files=no"], text=True, timeout=15)
        except (subprocess.SubprocessError, OSError) as error:
            raise RuntimeError("The managed Fooocus folder is not the pinned checkout; preserve it and move it aside before retrying.") from error
        if revision != FOOOCUS_SOURCE_REVISION or changes.strip():
            raise RuntimeError("The managed Fooocus checkout was changed; preserve it and move it aside before retrying.")
        return target
    temporary = Path(tempfile.mkdtemp(prefix="phone_studio_fooocus_", dir=custom_nodes_root))
    try:
        subprocess.run(["git", "init", "-q", str(temporary)], check=True, timeout=30)
        subprocess.run(["git", "-C", str(temporary), "remote", "add", "origin", "https://github.com/Acly/comfyui-inpaint-nodes.git"], check=True, timeout=30)
        subprocess.run(["git", "-C", str(temporary), "fetch", "-q", "--depth", "1", "origin", FOOOCUS_SOURCE_REVISION], check=True, timeout=90)
        subprocess.run(["git", "-C", str(temporary), "checkout", "-q", "--detach", "FETCH_HEAD"], check=True, timeout=30)
        revision = subprocess.check_output(["git", "-C", str(temporary), "rev-parse", "HEAD"], text=True, timeout=15).strip()
        if revision != FOOOCUS_SOURCE_REVISION:
            raise RuntimeError("Fooocus source revision verification failed.")
        os.replace(temporary, target)
        return target
    finally:
        if temporary.exists():
            # This is our freshly created, confined temporary checkout only.
            shutil.rmtree(temporary)


def setup_worker_editing(custom_nodes_root: str | Path, models_root: str | Path,
                         enabled: bool = True, reserve_gb: float = 8) -> dict:
    """Request the free auxiliary by default; failure keeps honest stock edits.

    Comfy's existing dependencies must supply Torch/NumPy/Kornia. No package
    resolver is allowed to upgrade these or install a different CUDA runtime.
    """
    result = {"requested": bool(enabled), "ready": False, "sourceRevision": FOOOCUS_SOURCE_REVISION,
              "weightsRevision": FOOOCUS_WEIGHTS_REVISION,
              "message": "Stock SDXL editing is available; Fooocus is disabled."}
    if not enabled:
        return result
    try:
        for module in ("torch", "numpy", "kornia"):
            if importlib.util.find_spec(module) is None:
                raise RuntimeError(f"Fooocus needs the existing ComfyUI {module} dependency; it was not replaced or installed automatically.")
        custom_nodes_root, models_root = Path(custom_nodes_root).resolve(), Path(models_root).resolve()
        custom_nodes_root.mkdir(parents=True, exist_ok=True)
        model_dir = models_root / "inpaint"
        model_dir.mkdir(parents=True, exist_ok=True)
        # Install a source only after the required weights are verified. A
        # failed download must not leave an active partial custom-node install.
        for name in FOOOCUS_WEIGHTS:
            _download_weight(name, model_dir, reserve_gb)
        source = _install_source(custom_nodes_root)
        result.update(ready=True, message="Pinned Fooocus auxiliary prepared. Start or restart ComfyUI; startup node registration determines availability.",
                      sourcePath=str(source), weights={name: digest for name, (_, digest) in FOOOCUS_WEIGHTS.items()})
    except Exception as error:
        # No credentials are used by this public-download helper.
        result["message"] = f"Fooocus unavailable: {error}. Stock masked SDXL edits remain available."
    print("[phone-studio-edit]", result["message"])
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Prepare pinned optional SDXL inpaint support without replacing Torch/CUDA.")
    parser.add_argument("--custom-nodes-root", required=True)
    parser.add_argument("--models-root", required=True)
    parser.add_argument("--reserve-gb", type=float, default=8)
    args = parser.parse_args()
    print(json.dumps(setup_worker_editing(args.custom_nodes_root, args.models_root, reserve_gb=args.reserve_gb)))
