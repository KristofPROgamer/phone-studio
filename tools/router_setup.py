"""Colab/local-runtime setup for the pinned router LLM. Importing does no work.

Called by the router notebook on the user's GPU. Never replaces Torch/CUDA.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import runpy
import secrets
import signal
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from router.model_profile import (ARTIFACTS, MODEL_REPO, MODEL_REVISION,
                                  PRIMARY_PROFILE, SERVER_SETTINGS, get_profile)

LLAMA_COMMIT = "7fe450e19305b828c199d602c23a8337aaa1f03b"
GIB = 1024 ** 3
CPU_PROJECTOR_MESSAGE = "Vision projector is on CPU; the same model weights are retained and review may be slower."


class SetupError(RuntimeError):
    pass


def _run(args: list[str], *, timeout: int, cwd: Path | None = None,
         log: Path | None = None) -> str:
    try:
        if log is None:
            result = subprocess.run(args, cwd=cwd, timeout=timeout, check=True,
                                    capture_output=True, text=True)
            return result.stdout.strip()
        with log.open("a", encoding="utf-8") as output:
            subprocess.run(args, cwd=cwd, timeout=timeout, check=True,
                           stdout=output, stderr=subprocess.STDOUT, text=True)
        return ""
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        reason = ('timeout' if isinstance(exc, subprocess.TimeoutExpired)
                  else f'exit {exc.returncode}' if isinstance(exc, subprocess.CalledProcessError)
                  else type(exc).__name__)
        location = f"; inspect {log}" if log is not None else ""
        raise SetupError(f"Setup step {Path(args[0]).name} failed ({reason}){location}.") from exc


def _memory_available() -> int:
    # Share the membership/ancestor-aware budget with the diagnostic sampler.
    # Unknown effective limits cannot justify the explicit optional CPU retry.
    helper = runpy.run_path(str(Path(__file__).with_name('runtime_diagnostics.py')))
    return helper['available_memory']()


def provisional_vram_mib(profile: dict = PRIMARY_PROFILE) -> int:
    # File bytes are not allocator measurements. The separate allowances are
    # conservative admission estimates, pending actual text/four-image sampling.
    artifact_mib = (sum(a["size"] for a in profile["artifacts"]) + 1024**2 - 1) // 1024**2
    return artifact_mib + 1024 + 1024 + 2048  # compute, 8K context/images, headroom


def gpu_info(profile: dict = PRIMARY_PROFILE, *, log: Path | None = None) -> dict:
    try:
        raw = _run(["nvidia-smi", "--query-gpu=name,compute_cap,memory.total,memory.free",
                    "--format=csv,noheader,nounits"], timeout=15)
    except SetupError as exc:
        if log is not None:
            cause = exc.__cause__
            _private_diagnostic(log, 'gpu visibility', output=(getattr(cause, 'stderr', None)
                                or getattr(cause, 'stdout', None) or str(cause)),
                returncode=getattr(cause, 'returncode', None),
                timed_out=isinstance(cause, subprocess.TimeoutExpired))
        raise SetupError(f"GPU visibility/driver probe failed; no model was downloaded or loaded."
                         + (f" Inspect {log}." if log is not None else "")) from exc
    if log is not None:
        _private_diagnostic(log, 'gpu visibility', output=raw, returncode=0)
    try:
        name, capability, total, free = [value.strip() for value in raw.splitlines()[0].split(",")]
        major, minor = [int(value) for value in capability.split(".")]
        architecture = major * 10 + minor
        if architecture < 75:
            raise SetupError("The router LLM notebook requires a T4/SM75 or newer CUDA GPU.")
        estimate = provisional_vram_mib(profile)
        if int(float(total)) < estimate or int(float(free)) < estimate:
            raise SetupError(f"The {profile['name'].upper()} assistant's provisional preflight needs {estimate} MiB free VRAM (artifact bytes plus compute/context/2 GiB headroom); measured fit is still unverified. Check occupied GPU memory separately from host RAM.")
        return {"name": name, "architecture": architecture,
                "totalMiB": int(float(total)), "freeMiB": int(float(free)),
                "provisionalRequiredMiB": estimate}
    except (ValueError, IndexError) as exc:
        raise SetupError("The GPU memory/capability probe could not be read.") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_verified(cache_dir: Path, artifact: dict, *, total_timeout: int = 2400,
                      profile: dict = PRIMARY_PROFILE) -> Path:
    cache_dir = cache_dir.resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = (cache_dir / artifact["name"]).resolve()
    if path.parent != cache_dir:
        raise SetupError("The model-cache path is invalid.")
    if path.exists():
        if path.stat().st_size == artifact["size"] and _sha256(path) == artifact["sha256"]:
            print(f"Verified cached artifact: {path.name}")
            return path
        raise SetupError(f"Cached artifact {path.name} failed verification; remove that file and rerun setup.")
    if shutil.disk_usage(cache_dir).free < artifact["size"] + 8 * GIB:
        raise SetupError("Insufficient model-cache disk space: keep 8 GiB free after the pinned download.")
    partial = path.with_name(path.name + ".download-" + secrets.token_hex(8))
    url = f"https://huggingface.co/{profile['repository']}/resolve/{profile['revision']}/{artifact['name']}"
    started = time.monotonic()
    digest = hashlib.sha256()
    downloaded = 0
    last_report = -1
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "PhoneStudioRouter/2"})
        with urllib.request.urlopen(request, timeout=45) as response, partial.open("xb") as output:
            for chunk in iter(lambda: response.read(4 * 1024 * 1024), b""):
                if time.monotonic() - started > total_timeout:
                    raise SetupError("The pinned model download timed out; rerun setup later.")
                downloaded += len(chunk)
                if downloaded > artifact["size"]:
                    raise SetupError("The model download exceeded its pinned size.")
                output.write(chunk)
                digest.update(chunk)
                progress = downloaded * 100 // artifact["size"]
                if progress // 10 != last_report:
                    print(f"Downloading {artifact['name']}: {progress}%")
                    last_report = progress // 10
            output.flush()
            os.fsync(output.fileno())
        if downloaded != artifact["size"] or digest.hexdigest() != artifact["sha256"]:
            raise SetupError("The model download failed its pinned size/hash check.")
        os.replace(partial, path)
        return path
    except (OSError, urllib.error.URLError) as exc:
        raise SetupError("The pinned model download failed; rerun setup later.") from exc
    finally:
        if partial.exists():
            partial.unlink()


PREBUILT_RELEASE = 'b11146'
PREBUILT_COMMIT = '7fe450e19305b828c199d602c23a8337aaa1f03b'
PREBUILT_ARTIFACTS = (
    {'name': 'llama-b11146-bin-ubuntu-cuda-12.8-x64.tar.gz', 'size': 168920581,
     'sha256': 'c2ab9e19838513ff69d1af8d999ad717dd3c7ee4714ac04c7ed5ab9077c50e4e'},
    {'name': 'cudart-llama-b11146-bin-ubuntu-cuda-12.8-x64.tar.gz', 'size': 594373356,
     'sha256': '1466daea60aad1144819e151b2bae19d54556cf1da6c129c4f55a5ded2637c25'},
)


def _prebuilt_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _prebuilt_download(root, artifact):
    path = root / artifact['name']
    if path.is_file():
        if path.stat().st_size == artifact['size'] and _prebuilt_hash(path) == artifact['sha256']:
            return path
        raise RuntimeError('A cached prebuilt archive failed verification; preserve it and move it aside before retrying.')
    partial = path.with_name(path.name + '.download')
    if partial.exists():
        raise RuntimeError('A prebuilt download is already present; confirm its owner before retrying.')
    request = urllib.request.Request(
        f'https://github.com/ggml-org/llama.cpp/releases/download/{PREBUILT_RELEASE}/{artifact["name"]}',
        headers={'User-Agent': 'PhoneStudio-prebuilt'})
    digest, downloaded = hashlib.sha256(), 0
    started = last_report = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=45) as response, partial.open('xb') as output:
            for chunk in iter(lambda: response.read(4 * 1024 * 1024), b''):
                downloaded += len(chunk)
                if downloaded > artifact['size'] or time.monotonic() - started > 300:
                    raise RuntimeError('The pinned prebuilt download exceeded its size or five-minute limit.')
                digest.update(chunk)
                output.write(chunk)
                if time.monotonic() - last_report > 10:
                    print(f'Downloading {artifact["name"]}: {downloaded * 100 // artifact["size"]}%')
                    last_report = time.monotonic()
            output.flush()
            os.fsync(output.fileno())
        if downloaded != artifact['size'] or digest.hexdigest() != artifact['sha256']:
            raise RuntimeError('The official prebuilt archive failed its pinned size/hash check.')
        os.replace(partial, path)
    finally:
        partial.unlink(missing_ok=True)
    return path


def _prebuilt_extract(archive, destination):
    # Write regular files first; internal library symlinks are created afterward.
    # No archive can write through a symlink or outside this fresh owned directory.
    destination = destination.resolve()
    with tarfile.open(archive, 'r:gz') as packed:
        members = packed.getmembers()
        if len(members) > 1000 or sum(m.size for m in members) > 6 * 1024**3:
            raise RuntimeError('Unexpected prebuilt archive inventory/expanded size.')
        targets, names = [], set()
        for member in members:
            relative = PurePosixPath(member.name)
            if relative.is_absolute() or '..' in relative.parts or '\\' in member.name:
                raise RuntimeError('Unsafe prebuilt archive path.')
            target = destination.joinpath(*relative.parts)
            if not target.resolve().is_relative_to(destination) or str(relative) in names:
                raise RuntimeError('Duplicate/unsafe prebuilt archive member.')
            names.add(str(relative))
            if not (member.isdir() or member.isfile() or member.issym()):
                raise RuntimeError('Unsupported prebuilt archive member type.')
            if member.issym():
                link = PurePosixPath(member.linkname)
                if link.is_absolute() or '\\' in member.linkname or not target.parent.joinpath(*link.parts).resolve().is_relative_to(destination):
                    raise RuntimeError('Unsafe prebuilt library symlink.')
            targets.append((member, target))
        for member, target in targets:
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                with packed.extractfile(member) as source, target.open('xb') as output:
                    shutil.copyfileobj(source, output)
                os.chmod(target, member.mode & 0o755)
        for member, target in targets:
            if member.issym():
                target.symlink_to(member.linkname)
        for member, target in targets:
            if member.issym() and not target.resolve(strict=True).is_relative_to(destination):
                raise RuntimeError('Prebuilt library symlink escaped its directory.')


@contextmanager
def _exclusive_lock(root: Path, name: str):
    lock = root / name
    owner = json.dumps({"pid": os.getpid(), "token": secrets.token_hex(16),
                        "created": time.time()})
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise SetupError(f"Setup is locked at {lock}; confirm the recorded owner has stopped before moving a stale lock aside.") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(owner)
        yield
    finally:
        # Never unlink a lock replaced by a different execution.
        try:
            if lock.read_text(encoding="utf-8") == owner:
                lock.unlink()
        except OSError:
            pass


def _private_diagnostic(log: Path, stage: str, *, output="", returncode=None,
                        timed_out=False) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    record = json.dumps({"stage": stage, "returnCode": returncode,
                         "timeout": timed_out, "output": str(output)[-16384:]}) + "\n"
    old = ''
    if log.is_file():
        with log.open('rb') as source:
            source.seek(max(0, log.stat().st_size - 98304))
            old = source.read(98304).decode('utf-8', errors='replace')
    log.write_text(old + record, encoding="utf-8")
    os.chmod(log, 0o600)


def _manifest(directory: Path) -> list[dict]:
    directory = directory.resolve()
    result = []
    for path in sorted(directory.rglob("*")):
        name = path.relative_to(directory).as_posix()
        if path.is_symlink():
            if not path.resolve(strict=True).is_relative_to(directory):
                raise SetupError("Installed library symlink is outside the private library directory.")
            result.append({"path": name, "kind": "symlink", "target": os.readlink(path)})
        elif path.is_file():
            result.append({"path": name, "kind": "file", "bytes": path.stat().st_size,
                           "mode": path.stat().st_mode & 0o777, "sha256": _sha256(path)})
        elif not path.is_dir():
            raise SetupError("Installed prebuilt contains an unsupported file type.")
    return result


def _manifest_digest(manifest: list[dict]) -> str:
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _prebuilt_environment(library_path: Path) -> dict:
    environment = os.environ.copy()
    for name in list(environment):
        if name.startswith(('PHONE_STUDIO_', 'NGROK_', 'TUNNEL_', 'CIVITAI_', 'LLAMA_')):
            environment.pop(name)
    environment['LD_LIBRARY_PATH'] = str(library_path) + os.pathsep + environment.get('LD_LIBRARY_PATH', '')
    return environment


def _probe_prebuilt(binary: Path, log: Path) -> None:
    for flag in ('--version', '--list-devices'):
        stage = 'prebuilt ' + flag
        try:
            result = subprocess.run([str(binary), flag], env=_prebuilt_environment(binary.parent),
                                    capture_output=True, text=True, timeout=45, check=True)
            output = result.stdout + result.stderr
            _private_diagnostic(log, stage, output=output, returncode=result.returncode)
        except subprocess.CalledProcessError as exc:
            _private_diagnostic(log, stage, output=(exc.stdout or '') + (exc.stderr or ''), returncode=exc.returncode)
            raise SetupError(f"{stage} failed (exit {exc.returncode}); inspect {log}. No model was loaded.") from exc
        except subprocess.TimeoutExpired as exc:
            output = str(exc.stdout or '') + str(exc.stderr or '')
            _private_diagnostic(log, stage, output=output, timed_out=True)
            raise SetupError(f"{stage} timed out after 45 seconds; inspect {log}. No model was loaded.") from exc
        except OSError as exc:
            _private_diagnostic(log, stage, output=f"{type(exc).__name__}: {exc}")
            raise SetupError(f"{stage} could not execute; inspect {log}. No model was loaded.") from exc
        if flag == '--version' and PREBUILT_COMMIT[:7] not in output:
            raise SetupError(f"The prebuilt version does not identify the pinned commit; inspect {log}.")
        if flag == '--list-devices' and not re.search(r'CUDA\d+\s*:', output):
            raise SetupError(f"The verified binary did not discover a CUDA GPU; inspect {log}. No model was loaded.")
        print(output.strip()[:2000])


def _verified_prebuilt_install(target: Path) -> dict | None:
    if target.is_symlink() or (target / 'llama-b11146').is_symlink():
        return None
    stamp = target / 'verified-prebuilt.json'
    if not stamp.is_file() or stamp.is_symlink():
        return None
    try:
        stored = json.loads(stamp.read_text(encoding='utf-8'))
        expected_archives = [dict(a) for a in PREBUILT_ARTIFACTS]
        if (stored.get('release') != PREBUILT_RELEASE or stored.get('commit') != PREBUILT_COMMIT
                or stored.get('archives') != expected_archives):
            return None
        actual = _manifest(target / 'llama-b11146')
        if actual != stored.get('files') or _manifest_digest(actual) != stored.get('integritySha256'):
            return None
        return stored
    except (OSError, ValueError, RuntimeError):
        return None


def prepare_prebuilt(root='/content/phone_studio_llm_prebuilt'):
    if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'amd64'):
        raise RuntimeError('This pinned prebuilt requires Linux x86_64.')
    libc, libc_version = platform.libc_ver()
    if libc != 'glibc' or tuple(int(v) for v in libc_version.split('.')[:2]) < (2, 38):
        raise RuntimeError('This official prebuilt requires glibc 2.38+; no system libraries were replaced.')
    root = Path(root).expanduser()
    if root.is_symlink():
        raise RuntimeError('Prebuilt storage must not be a symlink.')
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / PREBUILT_RELEASE
    binary = target / 'llama-b11146' / 'llama-server'
    log = root / 'setup-probes.log'
    with _exclusive_lock(root, '.prebuilt-setup.lock'):
        stored = _verified_prebuilt_install(target)
        if target.exists() and stored is None:
            raise SetupError(f"Unknown, unstamped or changed prebuilt directory preserved at {target}. Confirm its owner is idle, then move only that directory aside to a dated quarantine and retry; no directory was removed.")
        if stored is None:
            missing_archives = sum(a['size'] for a in PREBUILT_ARTIFACTS if not (root / a['name']).is_file())
            if shutil.disk_usage(root).free < missing_archives + 12 * GIB:
                raise SetupError('The isolated prebuilt needs archive/extraction space above an 8 GiB disk reserve.')
            archives = [_prebuilt_download(root, artifact) for artifact in PREBUILT_ARTIFACTS]
            with tempfile.TemporaryDirectory(prefix='prebuilt-stage-', dir=root) as staging_name:
                staging = Path(staging_name)
                try:
                    for archive in archives:
                        _prebuilt_extract(archive, staging)
                    lib_root = staging / 'llama-b11146'
                    runtime_root = staging / 'cudart-llama-b11146-bin-ubuntu-cuda-12.8-x64'
                    for name in ('libcudart.so.12', 'libcublas.so.12', 'libcublasLt.so.12'):
                        source = runtime_root / name
                        if not source.is_file() or source.is_symlink():
                            raise SetupError('A pinned CUDA runtime library is missing or not regular.')
                        shutil.copyfile(source, lib_root / name)
                    stage_binary = lib_root / 'llama-server'
                    if not stage_binary.is_file() or stage_binary.is_symlink():
                        raise SetupError('The verified archive has no regular server binary.')
                    _probe_prebuilt(stage_binary, log)
                    files = _manifest(lib_root)
                    stored = {'release': PREBUILT_RELEASE, 'commit': PREBUILT_COMMIT,
                              'archives': PREBUILT_ARTIFACTS, 'files': files,
                              'integritySha256': _manifest_digest(files)}
                    (staging / 'verified-prebuilt.json').write_text(json.dumps(stored, indent=2) + '\n', encoding='utf-8')
                    staging.rename(target)  # Publish only the probed, stamped complete install.
                except Exception as exc:
                    _private_diagnostic(log, 'prebuilt staging', output=f'{type(exc).__name__}: {exc}')
                    raise SetupError(f"Prebuilt staging failed; inspect {log}. This attempt's staging was removed; verified archives remain reusable.") from exc
        else:
            _probe_prebuilt(binary, log)
    print('Same-commit official prebuilt ready; no compilation or Torch/CUDA replacement performed.')
    return {'binary': str(binary), 'release': PREBUILT_RELEASE, 'commit': PREBUILT_COMMIT,
            'libraryPath': str(binary.parent), 'installationRoot': str(target),
            'integritySha256': stored['integritySha256']}



def _validated_build_timeout(value: int) -> int:
    if type(value) is not int or not 600 <= value <= 7200:
        raise SetupError("CUDA build timeout must be an integer from 600 to 7200 seconds (10 to 120 minutes).")
    return value


def build_server(build_dir: Path, architecture: int, *, build_timeout: int = 5400) -> Path:
    build_timeout = _validated_build_timeout(build_timeout)
    build_dir = build_dir.resolve()
    build_dir.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(build_dir).free < 10 * GIB:
        raise SetupError("Server build needs 2 GiB scratch above the 8 GiB disk reserve.")
    if _memory_available() < 4 * GIB:
        raise SetupError("Server build needs at least 4 GiB available host memory.")
    source = build_dir / "llama.cpp"
    output = source / "build" / "bin" / "llama-server"
    stamp = build_dir / "server-build.json"
    expected = {"commit": LLAMA_COMMIT, "architecture": architecture}
    if (source / ".git").exists():
        origin = _run(["git", "remote", "get-url", "origin"], timeout=15, cwd=source)
        changes = _run(["git", "status", "--porcelain", "--untracked-files=no"], timeout=15, cwd=source)
        if origin != "https://github.com/ggml-org/llama.cpp.git" or changes:
            raise SetupError("The managed server source was changed; preserve it and move it aside before retrying.")
    if stamp.exists() and output.is_file():
        try:
            if json.loads(stamp.read_text()) == expected:
                head = _run(["git", "rev-parse", "HEAD"], timeout=15, cwd=source)
                if head == LLAMA_COMMIT:
                    print("Reusing the pinned CUDA server build.")
                    return output
        except (ValueError, SetupError):
            pass
    log = build_dir / "setup.log"
    if not shutil.which("cmake") or not shutil.which("git") or not shutil.which("nvcc"):
        raise SetupError("This runtime needs its existing CUDA toolkit, git and CMake; no CUDA replacement is installed.")
    source.mkdir(parents=True, exist_ok=True)
    if not (source / ".git").exists():
        _run(["git", "init"], timeout=30, cwd=source, log=log)
        _run(["git", "remote", "add", "origin", "https://github.com/ggml-org/llama.cpp.git"],
             timeout=30, cwd=source, log=log)
    _run(["git", "fetch", "--depth", "1", "origin", LLAMA_COMMIT], timeout=300, cwd=source, log=log)
    _run(["git", "checkout", "--detach", "FETCH_HEAD"], timeout=60, cwd=source, log=log)
    if _run(["git", "rev-parse", "HEAD"], timeout=15, cwd=source) != LLAMA_COMMIT:
        raise SetupError("The server source did not match its pinned revision.")
    print(f"Building the pinned CUDA server for SM{architecture}; limit {build_timeout / 60:g} minutes, two compiler jobs. This is startup cost, not per-image work.")
    print(f"Compiler progress is written to {log}; CUDA compilation can take several minutes between updates.")
    _run(["cmake", "-S", str(source), "-B", str(source / "build"), "-DGGML_CUDA=ON",
          "-DCMAKE_BUILD_TYPE=Release", f"-DCMAKE_CUDA_ARCHITECTURES={architecture}",
          "-DLLAMA_BUILD_TESTS=OFF", "-DLLAMA_BUILD_EXAMPLES=OFF", "-DLLAMA_BUILD_TOOLS=ON",
          "-DLLAMA_BUILD_SERVER=ON", "-DLLAMA_BUILD_APP=OFF", "-DLLAMA_BUILD_UI=OFF",
          "-DLLAMA_USE_PREBUILT_UI=OFF", "-DLLAMA_SUBPROCESS=OFF", "-DLLAMA_OPENSSL=OFF"],
         timeout=300, log=log)
    try:
        _run(["cmake", "--build", str(source / "build"), "--config", "Release", "-j", "2",
              "--target", "llama-server"], timeout=build_timeout, log=log)
    except SetupError as error:
        if isinstance(error.__cause__, subprocess.TimeoutExpired):
            raise SetupError(
                f"CUDA build reached its {build_timeout / 60:g}-minute limit; inspect {log}. "
                "Compiler subprocesses may still be running. Confirm they have stopped before retrying; "
                "keep the build cache so completed compilation can be reused. No replacement model was selected."
            ) from error
        raise
    if not output.is_file():
        raise SetupError("The pinned server binary was not produced.")
    stamp.write_text(json.dumps(expected), encoding="utf-8")
    return output


def _stop(process: subprocess.Popen) -> None:
    if process.poll() is None:
        # Only called for a Popen created by this attempt with a new session.
        if platform.system() == "Linux":
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                process.wait(timeout=15)
                return
        else:
            process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            if platform.system() == "Linux":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                process.kill()
            process.wait(timeout=15)


def _server_ready(port: int, api_key: str, model_repo: str = MODEL_REPO) -> bool:
    class NoRedirects(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, file_pointer, code, message, headers, new_url):
            return None

    headers = {"Authorization": "Bearer " + api_key}
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirects())
        for endpoint in ("health", "props", "v1/models"):
            request = urllib.request.Request(f"http://127.0.0.1:{port}/{endpoint}", headers=headers)
            with opener.open(request, timeout=3) as response:
                data = json.loads(response.read(128 * 1024))
            if not isinstance(data, dict):
                return False
            if endpoint == "props":
                modalities = data.get("modalities", {})
                if not isinstance(modalities, dict) or modalities.get("vision") is not True:
                    return False
            if endpoint == "v1/models" and model_repo not in {
                    item.get("id") for item in data.get("data", []) if isinstance(item, dict)}:
                return False
        return True
    except (OSError, ValueError, TypeError, urllib.error.URLError):
        return False


def _session_identity(profile: dict, port: int, server_source: str, cpu_projector: bool) -> dict:
    return {"repository": profile['repository'], "revision": profile['revision'],
            "artifacts": profile['artifacts'], "serverCommit": LLAMA_COMMIT,
            "serverSource": server_source, "settings": SERVER_SETTINGS,
            "port": port, "projectorPlacement": "cpu" if cpu_projector else "gpu",
            "commandPolicyVersion": 1}


def _fingerprint(identity: dict) -> str:
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _process_start(pid: int) -> str | None:
    try:
        # /proc stat command names may contain spaces or parentheses.
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def _existing_session(runtime_dir: Path, port: int, *, profile: dict = PRIMARY_PROFILE,
                      server_source: str = 'official prebuilt ' + PREBUILT_RELEASE,
                      cpu_projector_fallback: bool = False) -> dict | None:
    session_file = runtime_dir / "llm-session.json"
    if not session_file.exists():
        return None
    try:
        session = json.loads(session_file.read_text())
        if not isinstance(session, dict):
            return None
        placement = session.get('projectorPlacement')
        if placement not in ('gpu', 'cpu') or (placement == 'cpu' and not cpu_projector_fallback):
            return None
        identity = _session_identity(profile, port, server_source, placement == 'cpu')
        pid = session.get('pid')
        if not isinstance(pid, int) or not session.get('processStart') or _process_start(pid) != session['processStart']:
            return None
        server_info = session.get('serverInfo', {})
        if not isinstance(server_info, dict):
            return None
        if server_source.startswith('official prebuilt'):
            stored = _verified_prebuilt_install(Path(server_info.get('installationRoot', '')))
            if not stored or stored['integritySha256'] != server_info.get('integritySha256'):
                return None
        elif not Path(session.get('binary', '')).is_file() or _sha256(Path(session['binary'])) != session.get('binarySha256'):
            return None
        if (session.get('fingerprint') == _fingerprint(identity)
                and session.get("port") == port
                and _server_ready(port, session["apiKey"], profile['repository'])):
            environment = session["environment"]
            if (not isinstance(environment, dict)
                    or environment.get("PHONE_STUDIO_LLM_URL") != f"http://127.0.0.1:{port}"
                    or environment.get("PHONE_STUDIO_LLM_API_KEY") != session["apiKey"]
                    or environment.get("PHONE_STUDIO_LLM_DEGRADED") != (CPU_PROJECTOR_MESSAGE if placement == 'cpu' else '')
                    or environment.get("PHONE_STUDIO_LLM_MODEL") != profile['repository']
                    or environment.get("PHONE_STUDIO_LLM_REVISION") != profile['revision']
                    or environment.get("PHONE_STUDIO_LLM_FINGERPRINT") != session['fingerprint']):
                return None
            print("Reusing the existing pinned LLM process.")
            os.environ.update(environment)
            return {"environment": environment, "process": None,
                    "pid": pid, "reused": True, "fingerprint": session['fingerprint'],
                    "profile": profile, "serverSource": server_source,
                    "serverInfo": server_info, "gpu": session.get('gpu'),
                    "projectorPlacement": placement,
                    "placementEvidence": session.get('placementEvidence'),
                    "artifacts": [{"filename": a['name'], "bytes": a['size'], "sha256": a['sha256']}
                                  for a in profile['artifacts']]}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def start_server(binary: Path, weights: Path, projector: Path, runtime_dir: Path,
                 *, port: int = 8081, startup_timeout: int = 600,
                 cpu_projector_fallback: bool = False,
                 native_library_path: str | None = None,
                 profile: dict = PRIMARY_PROFILE, server_info: dict | None = None,
                 gpu: dict | None = None) -> dict:
    if not 1024 <= port <= 65535:
        raise SetupError("The local LLM port is invalid.")
    if type(startup_timeout) is not int or not 1 <= startup_timeout <= 1800:
        raise SetupError("Startup timeout must be an integer from 1 to 1800 seconds.")
    if type(cpu_projector_fallback) is not bool:
        raise SetupError("CPU-projector fallback must be true or false.")
    if runtime_dir.is_symlink():
        raise SetupError("Runtime storage must not be a symlink.")
    runtime_dir = runtime_dir.expanduser().resolve()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    with _exclusive_lock(runtime_dir, '.llm-startup.lock'):
        return _start_server_locked(binary, weights, projector, runtime_dir,
            port=port, startup_timeout=startup_timeout,
            cpu_projector_fallback=cpu_projector_fallback,
            native_library_path=native_library_path, profile=profile,
            server_info=server_info, gpu=gpu)


def _log_tail(log: Path, offset: int = 0) -> str:
    try:
        with log.open('rb') as source:
            source.seek(max(offset, log.stat().st_size - 65536))
            return source.read(65536).decode('utf-8', errors='replace')
    except OSError:
        return ''


def _startup_category(output: str, timed_out: bool) -> str:
    if re.search(r'(CUDA|cuda|cublas).*?(out of memory|allocation failed)|cudaMalloc.*?(failed|error)', output, re.S):
        return 'gpu_memory'
    if re.search(r'unknown (argument|option)|invalid (argument|option)|unrecognized option', output, re.I):
        return 'invalid_cli'
    if re.search(r'shared librar|GLIBC_|cannot open shared object', output, re.I):
        return 'loader_or_library'
    if re.search(r'unsupported.*(architecture|model)|failed to load (model|mmproj)|invalid.*GGUF', output, re.I):
        return 'model_or_projector'
    return 'startup_timeout' if timed_out else 'process_exit'


def _placement_evidence(output: str, cpu_projector: bool) -> dict:
    layers = re.search(r'offloaded\s+(\d+)\s*/\s*(\d+)\s+layers to GPU', output, re.I)
    return {'projectorRequested': 'cpu' if cpu_projector else 'gpu',
            'observedGpuLayers': int(layers[1]) if layers else None,
            'observedTotalLayers': int(layers[2]) if layers else None,
            'fitPolicy': SERVER_SETTINGS['fit'],
            'note': 'Read the private startup log for actual projector/backend placement; absent layer counts are unavailable, not zero.'}


def _start_server_locked(binary: Path, weights: Path, projector: Path, runtime_dir: Path,
                 *, port: int, startup_timeout: int, cpu_projector_fallback: bool,
                 native_library_path: str | None, profile: dict,
                 server_info: dict | None, gpu: dict | None) -> dict:
    server_source = 'official prebuilt ' + PREBUILT_RELEASE if server_info else 'explicit source build'
    # A notebook rerun must not launch a second process or attach to an unrelated server.
    session_file = runtime_dir / "llm-session.json"
    existing = _existing_session(runtime_dir, port, profile=profile, server_source=server_source,
                                 cpu_projector_fallback=cpu_projector_fallback)
    if existing:
        return existing
    # Bind check is local and never sends credentials to an unknown process.
    import socket
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as exc:
            raise SetupError("The private LLM port is occupied by a session that does not match this profile/settings/integrity. Preserve it; stop only its verified owned process when idle or select a free supported port. No existing process was stopped.") from exc
    api_key = secrets.token_urlsafe(32)
    key_file = runtime_dir / "llm-api-key.txt"
    key_file.write_text(api_key, encoding="utf-8")
    os.chmod(key_file, 0o600)
    log = runtime_dir / "llama-server.log"
    common = [str(binary), "--model", str(weights), "--mmproj", str(projector),
        "--alias", profile['repository'], "--host", "127.0.0.1", "--port", str(port),
        "--api-key-file", str(key_file), "--ctx-size", str(SERVER_SETTINGS['context']),
        "--parallel", str(SERVER_SETTINGS['parallel']),
        "--batch-size", str(SERVER_SETTINGS['batch']), "--ubatch-size", str(SERVER_SETTINGS['microbatch']),
        "--fit", SERVER_SETTINGS['fit'], "--fit-target", str(SERVER_SETTINGS['fitTargetMiB']),
        "--flash-attn", SERVER_SETTINGS['flashAttention'], "--cache-type-k", SERVER_SETTINGS['cacheK'],
        "--cache-type-v", SERVER_SETTINGS['cacheV'], "--image-min-tokens", str(SERVER_SETTINGS['imageMinTokens']),
        "--image-max-tokens", str(SERVER_SETTINGS['imageMaxTokens']),
        "--mtmd-batch-max-tokens", str(SERVER_SETTINGS['mtmdBatchMaxTokens']), "--jinja", "--no-webui", "--no-agent",
        "--no-webui-mcp-proxy",
        "--chat-template-kwargs", '{"enable_thinking":false}',
        "--cache-ram", str(SERVER_SETTINGS['cacheRamMiB']), "--log-verbosity", "2"]
    for cpu_projector in ([False, True] if cpu_projector_fallback else [False]):
        command = common + (["--no-mmproj-offload"] if cpu_projector else [])
        message = CPU_PROJECTOR_MESSAGE if cpu_projector else ""
        print("Starting one private LLM process" + (" with CPU vision projector." if cpu_projector else "."))
        environment = os.environ.copy()
        # The native model process needs GPU configuration, not worker/router
        # credentials or inherited command/file-tool configuration.
        for name in list(environment):
            if name.startswith(("PHONE_STUDIO_", "NGROK_", "TUNNEL_", "CIVITAI_", "LLAMA_")):
                environment.pop(name)
        if native_library_path is not None:
            environment['LD_LIBRARY_PATH'] = native_library_path + os.pathsep + environment.get('LD_LIBRARY_PATH', '')
        process, published = None, False
        offset = log.stat().st_size if log.exists() else 0
        try:
            with log.open("a", encoding="utf-8") as output:
                os.chmod(log, 0o600)
                process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT,
                                           env=environment, start_new_session=True)
            started = time.monotonic()
            while process.poll() is None and time.monotonic() - started < startup_timeout:
                if _server_ready(port, api_key, profile['repository']):
                    identity = _session_identity(profile, port, server_source, cpu_projector)
                    fingerprint = _fingerprint(identity)
                    env = {"PHONE_STUDIO_LLM_URL": f"http://127.0.0.1:{port}",
                        "PHONE_STUDIO_LLM_API_KEY": api_key,
                        "PHONE_STUDIO_LLM_MODEL": profile['repository'],
                        "PHONE_STUDIO_LLM_REVISION": profile['revision'],
                        "PHONE_STUDIO_LLM_FINGERPRINT": fingerprint,
                        "PHONE_STUDIO_LLM_DEGRADED": message}
                    session = {"commit": LLAMA_COMMIT, "revision": profile['revision'],
                        "pid": process.pid, "processStart": _process_start(process.pid),
                        "binary": str(binary.resolve()), "binarySha256": _sha256(binary),
                        "port": port, "apiKey": api_key, "environment": env,
                        "identity": identity, "fingerprint": fingerprint, 'gpu': gpu,
                        "serverInfo": server_info or {},
                        "placementEvidence": _placement_evidence(_log_tail(log, offset), cpu_projector),
                        "projectorPlacement": 'cpu' if cpu_projector else 'gpu'}
                    staging_session = session_file.with_name('llm-session.json.stage-' + secrets.token_hex(8))
                    try:
                        with staging_session.open('x', encoding='utf-8') as output:
                            os.chmod(staging_session, 0o600)
                            json.dump(session, output)
                            output.flush()
                            os.fsync(output.fileno())
                        os.replace(staging_session, session_file)
                    finally:
                        staging_session.unlink(missing_ok=True)
                    published = True
                    os.environ.update(env)
                    print("Assistant process/vision are ready; application inference acceptance is still required. " + message)
                    return {"environment": env, "process": process, "pid": process.pid,
                        "reused": False, "fingerprint": fingerprint, "profile": profile,
                        "serverSource": server_source, "serverInfo": server_info or {},
                        "gpu": gpu, "projectorPlacement": session['projectorPlacement'],
                        "placementEvidence": session['placementEvidence'],
                        "artifacts": [{"filename": a['name'], "bytes": a['size'], "sha256": a['sha256']}
                                      for a in profile['artifacts']]}
                time.sleep(2)
            timed_out = process.poll() is None
            category = _startup_category(_log_tail(log, offset), timed_out)
            _private_diagnostic(runtime_dir / 'setup-startup.log', 'llm startup',
                                output=category, returncode=process.poll(), timed_out=timed_out)
        except OSError as exc:
            _private_diagnostic(runtime_dir / 'setup-startup.log', 'llm launch/publication',
                                output=f'{type(exc).__name__}: {exc}')
            raise SetupError(f"Assistant launch/session publication failed; inspect {runtime_dir / 'setup-startup.log'}. Only this attempt's process was stopped.") from exc
        finally:
            if process is not None and not published:
                _stop(process)
        # The explicit opt-in retry is limited to demonstrated GPU placement OOM.
        # Moving the projector to CPU requires separate available-host-RAM evidence.
        if (not cpu_projector and cpu_projector_fallback and category == 'gpu_memory'
                and _memory_available() >= sum(a['size'] for a in profile['artifacts']) + 4 * GIB):
            print('Confirmed GPU allocation failure; explicit CPU-projector opt-in has sufficient available host RAM. One degraded retry.')
            continue
        raise SetupError(f"Assistant startup failed ({category}); inspect {log} and {runtime_dir / 'setup-startup.log'}. No automatic model replacement or unrelated restart was performed.")
    raise SetupError(f"The explicit CPU-projector retry failed; inspect {log}.")


def setup_runtime(cache_dir: str = "/content/phone_studio_llm_models",
                  build_dir: str = "/content/phone_studio_llm_build",
                  runtime_dir: str = "/content/phone_studio_llm",
                  *, port: int = 8081, cpu_projector_fallback: bool = False,
                  build_timeout: int = 5400,
                  use_prebuilt: bool = True, allow_source_build: bool = False,
                  prebuilt_dir: str = "/content/phone_studio_llm_prebuilt",
                  model_profile: str = "4b", quality_fallback_confirmed: bool = False) -> dict:
    if sys.version_info < (3, 11):
        raise SetupError("The router notebook requires Python 3.11 or newer.")
    build_timeout = _validated_build_timeout(build_timeout)
    if type(use_prebuilt) is not bool or type(allow_source_build) is not bool:
        raise SetupError("Prebuilt/source-build settings must be true or false.")
    if not use_prebuilt and not allow_source_build:
        raise SetupError("No server setup method is enabled. Enable the verified prebuilt or explicitly allow source compilation.")
    try:
        profile = get_profile(model_profile, quality_fallback_confirmed=quality_fallback_confirmed)
    except ValueError as exc:
        raise SetupError(str(exc)) from exc
    runtime_root = Path(runtime_dir).expanduser()
    if runtime_root.is_symlink():
        raise SetupError("Runtime storage must not be a symlink.")
    runtime_root = runtime_root.resolve()
    runtime_root.mkdir(parents=True, exist_ok=True)
    with _exclusive_lock(runtime_root, '.runtime-setup.lock'):
        return _setup_runtime_locked(cache_dir, build_dir, runtime_root, port=port,
            cpu_projector_fallback=cpu_projector_fallback, build_timeout=build_timeout,
            use_prebuilt=use_prebuilt, allow_source_build=allow_source_build,
            prebuilt_dir=prebuilt_dir, profile=profile)


def _setup_runtime_locked(cache_dir: str, build_dir: str, runtime_dir: Path, *,
                  port: int, cpu_projector_fallback: bool, build_timeout: int,
                  use_prebuilt: bool, allow_source_build: bool,
                  prebuilt_dir: str, profile: dict) -> dict:
    # Once loaded, the model occupies GPU memory. Check authenticated reuse before
    # applying the free-memory guard intended for a fresh process.
    existing = _existing_session(runtime_dir, port, profile=profile,
        server_source='official prebuilt ' + PREBUILT_RELEASE if use_prebuilt else 'explicit source build',
        cpu_projector_fallback=cpu_projector_fallback)
    if existing:
        return existing
    gpu = gpu_info(profile, log=runtime_dir / 'setup-probes.log')
    print(f"Router GPU: {gpu['name']}, SM{gpu['architecture']}, {gpu['freeMiB']} MiB free. Fit is not a benchmark.")
    print(f"Available host RAM with verified accessible cgroup bounds: {_memory_available() / GIB:.2f} GiB (separate from GPU VRAM; zero means unavailable or exhausted).")
    local_cache = Path(cache_dir).expanduser().resolve() / (profile['name'] + '-' + profile['revision'])
    local_cache.mkdir(parents=True, exist_ok=True)
    needed = sum(item["size"] for item in profile['artifacts'] if not (local_cache / item["name"]).is_file())
    if shutil.disk_usage(local_cache).free < needed + 8 * GIB:
        raise SetupError(f"Selected {profile['name'].upper()} pair needs {needed / GIB:.3f} GiB of remaining downloads plus an 8 GiB disk reserve.")
    prebuilt = None
    if use_prebuilt:
        try:
            prebuilt = prepare_prebuilt(prebuilt_dir)
            binary = Path(prebuilt['binary'])
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            if not allow_source_build:
                raise SetupError(
                    f"The pinned official prebuilt could not start: {error}. "
                    "No source compilation was started; inspect compatibility and retry the same pinned binary."
                ) from error
            print('Verified prebuilt unavailable; source compilation was explicitly enabled.')
    if prebuilt is None:
        binary = build_server(Path(build_dir), gpu["architecture"], build_timeout=build_timeout)
    paths = [download_verified(local_cache, artifact, profile=profile) for artifact in profile['artifacts']]
    (local_cache / 'model-profile.json').write_text(json.dumps(profile, indent=2) + '\n', encoding='utf-8')
    result = start_server(binary, paths[0], paths[1], runtime_dir, port=port,
                          cpu_projector_fallback=cpu_projector_fallback,
                          native_library_path=prebuilt['libraryPath'] if prebuilt else None,
                          profile=profile, server_info=prebuilt, gpu=gpu)
    os.environ.update(result["environment"])
    return result


if __name__ == "__main__":
    result = setup_runtime()
    print(json.dumps({key: value for key, value in result.items()
                      if key not in {"environment", "process"}}, indent=2))
