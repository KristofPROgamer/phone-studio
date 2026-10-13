"""Pinned optional CPU SAM2 selection setup; importing installs nothing.

The router notebook calls setup_segmentation explicitly. Existing Torch/CUDA
remain untouched, and SAM's optional CUDA extension is disabled.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

SAM2_SOURCE_REVISION = "2b90b9f5ceec907a1c18123530e92e794ad901a4"
SAM2_WEIGHTS_REVISION = "de431c4043854a71d8101e17995dfe596bf101a5"
SAM2_WEIGHT_NAME = "sam2.1_hiera_tiny.pt"
SAM2_WEIGHT_BYTES = 156008466
SAM2_WEIGHT_SHA256 = "7402e0d864fa82708a20fbd15bc84245c2f26dff0eb43a4b5b93452deb34be69"
SAM2_CONFIG = "configs/sam2.1/sam2.1_hiera_t.yaml"
CPU_DEPENDENCIES = {
    "hydra-core": "1.3.2", "omegaconf": "2.3.0", "antlr4-python3-runtime": "4.9.3",
    "iopath": "0.1.10", "portalocker": "2.10.1",
}


def _file_hash(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def _check_dependencies() -> list[str]:
    from packaging.version import Version
    if sys.version_info < (3, 10):
        raise RuntimeError("Automatic selection needs Python 3.10 or newer.")
    for package, minimum in (("torch", "2.5.1"), ("torchvision", "0.20.1"),
                             ("numpy", "1.24.4"), ("Pillow", "9.4.0"), ("tqdm", "4.66.1")):
        try:
            version = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError as error:
            raise RuntimeError(f"Automatic selection needs existing {package}>={minimum}; the runtime packages were preserved.") from error
        if Version(version.split("+")[0]) < Version(minimum):
            raise RuntimeError(f"Automatic selection needs {package}>={minimum}; version {version} was preserved.")
    # Import in a short child process to detect the common torchvision ABI
    # mismatch without retaining Torch in the notebook's setup process. No GPU
    # context, native compilation or inference is requested by this check.
    check = subprocess.run([sys.executable, "-c", "import torch, torchvision; assert hasattr(torchvision, 'transforms')"],
                           timeout=45, capture_output=True, text=True)
    if check.returncode:
        raise RuntimeError("The existing Torch/torchvision packages are incompatible; automatic selection was skipped, without replacing them.")
    missing = []
    for package, version in CPU_DEPENDENCIES.items():
        try:
            installed = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            missing.append(f"{package}=={version}")
            continue
        if Version(installed) < Version(version):
            raise RuntimeError(f"Existing {package} is older than the pinned SAM requirement; preserve it and use a manual mask.")
    return missing


def _download_checkpoint(root: Path) -> Path:
    destination = root / SAM2_WEIGHT_NAME
    if destination.is_file() and destination.stat().st_size == SAM2_WEIGHT_BYTES and _file_hash(destination) == SAM2_WEIGHT_SHA256:
        return destination
    if destination.exists():
        raise RuntimeError("The existing SAM checkpoint differs from the pinned file; move it aside before retrying.")
    if shutil.disk_usage(root).free < SAM2_WEIGHT_BYTES + 2 * 1024**3:
        raise RuntimeError("Automatic selection needs its 149 MiB checkpoint plus 2 GiB of local disk reserve.")
    temporary = root / (SAM2_WEIGHT_NAME + "." + str(os.getpid()) + ".part")
    url = f"https://huggingface.co/facebook/sam2.1-hiera-tiny/resolve/{SAM2_WEIGHTS_REVISION}/{SAM2_WEIGHT_NAME}"
    hasher, received, started = hashlib.sha256(), 0, time.monotonic()
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "PhoneStudio-router-selection"})
        with urllib.request.urlopen(request, timeout=45) as response, temporary.open("xb") as handle:
            while block := response.read(2 * 1024 * 1024):
                received += len(block)
                if received > SAM2_WEIGHT_BYTES or time.monotonic() - started > 300:
                    raise RuntimeError("SAM checkpoint download exceeded its bounded size/time.")
                hasher.update(block)
                handle.write(block)
        if received != SAM2_WEIGHT_BYTES or hasher.hexdigest() != SAM2_WEIGHT_SHA256:
            raise RuntimeError("SAM checkpoint publisher-file integrity check failed.")
        os.replace(temporary, destination)
        return destination
    finally:
        temporary.unlink(missing_ok=True)


def _source_checkout(root: Path) -> Path:
    target = root / "source"
    if target.exists():
        revision = subprocess.check_output(["git", "-C", str(target), "rev-parse", "HEAD"], text=True, timeout=15).strip()
        changes = subprocess.check_output(["git", "-C", str(target), "status", "--porcelain", "--untracked-files=no"], text=True, timeout=15)
        if revision != SAM2_SOURCE_REVISION or changes.strip():
            raise RuntimeError("The managed SAM source was changed; preserve it and move it aside before retrying.")
        return target
    temporary = Path(tempfile.mkdtemp(prefix="sam_source_", dir=root))
    try:
        subprocess.run(["git", "init", "-q", str(temporary)], check=True, timeout=30)
        subprocess.run(["git", "-C", str(temporary), "remote", "add", "origin", "https://github.com/facebookresearch/sam2.git"], check=True, timeout=30)
        subprocess.run(["git", "-C", str(temporary), "fetch", "-q", "--depth", "1", "origin", SAM2_SOURCE_REVISION], check=True, timeout=90)
        subprocess.run(["git", "-C", str(temporary), "checkout", "-q", "--detach", "FETCH_HEAD"], check=True, timeout=30)
        if subprocess.check_output(["git", "-C", str(temporary), "rev-parse", "HEAD"], text=True, timeout=15).strip() != SAM2_SOURCE_REVISION:
            raise RuntimeError("SAM source revision verification failed.")
        os.replace(temporary, target)
        return target
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def setup_segmentation(enabled: bool = True, cache_dir: str | Path = "/content/phone_studio_sam2") -> dict:
    result = {"requested": bool(enabled), "ready": False, "device": "cpu", "env": {},
              "sourceRevision": SAM2_SOURCE_REVISION, "weightsRevision": SAM2_WEIGHTS_REVISION,
              "message": "Automatic selection disabled; manual selections remain available."}
    if not enabled:
        return result
    try:
        root = Path(cache_dir).resolve()
        root.mkdir(parents=True, exist_ok=True)
        if hasattr(os, "sysconf"):
            available_pages = os.sysconf("SC_AVPHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            if available_pages * page_size < 3 * 1024**3:
                raise RuntimeError("Automatic CPU selection needs at least 3 GiB of available host memory.")
        missing = _check_dependencies()
        checkpoint = _download_checkpoint(root)
        source = _source_checkout(root)
        if missing:
            subprocess.run([sys.executable, "-m", "pip", "install", "--no-deps", *missing], check=True, timeout=180)
        child_env = os.environ.copy()
        child_env["SAM2_BUILD_CUDA"] = "0"
        subprocess.run([sys.executable, "-m", "pip", "install", "--no-deps", "--no-build-isolation", "-e", str(source)],
                       check=True, timeout=180, env=child_env, cwd=root)
        # Do not claim inference was tested. This records verified setup only.
        result.update(ready=True, message="Pinned SAM2.1 Tiny CPU selection installed. Start or restart the router with the returned environment; mask quality remains unverified.",
                      env={"PHONE_STUDIO_SAM2_CHECKPOINT": str(checkpoint), "PHONE_STUDIO_SAM2_CONFIG": SAM2_CONFIG,
                           "PHONE_STUDIO_SAM2_SOURCE_REVISION": SAM2_SOURCE_REVISION})
    except Exception as error:
        result["message"] = f"Automatic selection unavailable: {type(error).__name__}: {error}. Paint a manual selection instead."
    print("[phone-studio-selection]", result["message"])
    return result


if __name__ == "__main__":
    import json
    print(json.dumps(setup_segmentation()))
