"""Optional, pinned T4 attention build for Colab; importing this file installs nothing.

Call install_t4_flash_attention() before starting ComfyUI. It returns a validated
manifest or None and preserves the existing PyTorch/CUDA packages. Three tiny GPU
numeric/stream checks run only when the user invokes the opt-in installer; they
are not a speed benchmark or a full-image quality check.

Source: https://github.com/ssiu/flash-attention-turing
"""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time


T4_FLASH_COMMIT = "9ef98fcb506bb1e2fe3cece50935e2935bf6b124"
T4_FLASH_CUTLASS_COMMIT = "df18f5e4f5de76bed8be1de8e4c245f2f5ec3020"
T4_FLASH_PATCH = "phone-studio-t4-forward-v1"
T4_FLASH_MODULE = "phone_studio_flash_attn_turing"
T4_FLASH_ROOT = Path("/content/phone_studio_t4_flash")
T4_FLASH_RUNTIME = T4_FLASH_ROOT / "runtime"
T4_FLASH_STAMP = T4_FLASH_ROOT / "install.json"
_GIB = 1024 ** 3
_SOURCE_HASHES = {
    "setup.py": "3788d57ad0d1fae5313cc3247fb4f3f4f8705d51f43deba3ad5399125134fddb",
    "csrc/flash_attn/flash_api.cpp": "a00f82a9be15f56fdd2e688cc098525b9939b708873e678a64c8da8f941cc9f4",
    "csrc/flash_attn/src/flash_fwd_launch_template.h":
        "edb12023488232b63c3e8c8c72801c93c559f35da13e302fcaf28100803cd0e8",
}


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _replace_once(text, before, after, label):
    if text.count(before) != 1:
        raise RuntimeError(f"Pinned source did not match the {label} patch")
    return text.replace(before, after, 1)


def _patch_source(source_dir):
    """Check upstream bytes, then patch only the audited forward entry point."""
    for relative, expected in _SOURCE_HASHES.items():
        if _sha256(source_dir / relative) != expected:
            raise RuntimeError(f"Pinned source checksum failed: {relative}")

    setup_path = source_dir / "setup.py"
    setup = setup_path.read_text(encoding="utf-8")
    setup = _replace_once(setup, '\n    name="flash_attn_turing",',
                          f'\n    name="{T4_FLASH_MODULE}",', "distribution name")
    setup = _replace_once(setup, '\n            name="flash_attn_turing",',
                          f'\n            name="{T4_FLASH_MODULE}",', "native extension name")
    # One noncausal head64 forward specialization is the actual SDXL target.
    # Remove every other compilation unit; the matching API trimming below also
    # removes their references so the resulting library has no unresolved symbols.
    units = [
        'csrc/flash_attn/src/flash_fwd_hdim64_fp16_causal_sm75.cu',
        'csrc/flash_attn/src/flash_fwd_hdim96_fp16_sm75.cu',
        'csrc/flash_attn/src/flash_fwd_hdim96_fp16_causal_sm75.cu',
        'csrc/flash_attn/src/flash_fwd_hdim128_fp16_sm75.cu',
        'csrc/flash_attn/src/flash_fwd_hdim128_fp16_causal_sm75.cu',
        'csrc/flash_attn/src/flash_bwd_hdim64_fp16_sm75.cu',
        'csrc/flash_attn/src/flash_bwd_hdim64_fp16_causal_sm75.cu',
        'csrc/flash_attn/src/flash_bwd_hdim96_fp16_sm75.cu',
        'csrc/flash_attn/src/flash_bwd_hdim96_fp16_causal_sm75.cu',
        'csrc/flash_attn/src/flash_bwd_hdim128_fp16_sm75.cu',
    ]
    for unit in units:
        setup = _replace_once(setup, f'                      "{unit}",\n', '',
                              f'unused compilation unit {unit}')
    setup = _replace_once(setup,
        '                      "csrc/flash_attn/src/flash_bwd_hdim128_fp16_causal_sm75.cu"\n',
        '', 'last unused compilation unit')
    setup_path.write_text(setup, encoding="utf-8")

    api_path = source_dir / "csrc/flash_attn/flash_api.cpp"
    api = api_path.read_text(encoding="utf-8")
    api = _replace_once(
        api, "#include <torch/extension.h>\n",
        "#include <torch/extension.h>\n#include <c10/cuda/CUDAGuard.h>\n"
        "#include <ATen/cuda/CUDAContext.h>\n#include <cmath>\n#include <cstdint>\n#include <limits>\n",
        "native device guard includes",
    )
    checks = """    TORCH_CHECK(q.dim() == 4 && k.dim() == 4 && v.dim() == 4,
                "Phone Studio T4 attention requires rank-4 tensors");
    TORCH_CHECK(q.is_cuda() && k.is_cuda() && v.is_cuda(),
                "Phone Studio T4 attention requires CUDA tensors");
    TORCH_CHECK(q.device() == k.device() && q.device() == v.device(),
                "Phone Studio T4 attention requires one CUDA device");
    TORCH_CHECK(q.scalar_type() == torch::kFloat16 &&
                k.scalar_type() == torch::kFloat16 && v.scalar_type() == torch::kFloat16,
                "Phone Studio T4 attention requires FP16 tensors");
    TORCH_CHECK(q.is_contiguous() && k.is_contiguous() && v.is_contiguous(),
                "Phone Studio T4 attention requires contiguous B,L,H,D tensors");
    TORCH_CHECK(reinterpret_cast<std::uintptr_t>(q.data_ptr()) % 16 == 0 &&
                reinterpret_cast<std::uintptr_t>(k.data_ptr()) % 16 == 0 &&
                reinterpret_cast<std::uintptr_t>(v.data_ptr()) % 16 == 0,
                "Phone Studio T4 attention requires 16-byte-aligned Q/K/V tensors");
    TORCH_CHECK(!q.requires_grad() && !k.requires_grad() && !v.requires_grad(),
                "Phone Studio T4 attention is inference-only");
    TORCH_CHECK(!is_causal && std::isfinite(softmax_scale) && softmax_scale > 0.0f,
                "Phone Studio T4 attention supports unmasked forward attention only");
    for (const auto &tensor : {q, k, v}) {
        TORCH_CHECK(tensor.numel() < std::numeric_limits<int>::max(),
                    "Phone Studio T4 attention tensor exceeds kernel indexing limits");
        for (const auto size : tensor.sizes()) {
            TORCH_CHECK(size > 0 && size < std::numeric_limits<int>::max(),
                        "Phone Studio T4 attention requires nonempty bounded tensors");
        }
    }
    TORCH_CHECK(q.size(3) == 64,
                "Phone Studio T4 attention supports SDXL head size 64");
    const c10::cuda::CUDAGuard device_guard(q.device());
    const auto properties = at::cuda::getCurrentDeviceProperties();
    TORCH_CHECK(properties->major == 7 && properties->minor == 5,
                "Phone Studio T4 attention requires SM7.5");
"""
    api = _replace_once(api, "    auto device = q.device();\n",
                        checks + "    auto device = q.device();\n", "forward argument checks")
    api = _replace_once(
        api,
        '    m.def("bwd", &mha_bwd, "Backward pass");\n'
        '    m.def("varlen_fwd", &mha_varlen_fwd, "Varlen forward pass");\n'
        '    m.def("varlen_bwd", &mha_varlen_bwd, "Varlen backward pass");\n',
        f'    m.attr("__phone_studio_patch__") = "{T4_FLASH_PATCH}";\n'
        f'    m.attr("__phone_studio_commit__") = "{T4_FLASH_COMMIT}";\n',
        "forward-only exported API",
    )
    # Keep the audited parameter builder and regular forward function. All
    # backward/varlen/general-dispatch functions are excluded from this private
    # inference build; their original files remain in the pinned checkout.
    anchors = ['void set_params_dgrad(', 'std::vector<at::Tensor>\nmha_fwd(',
               'std::vector<at::Tensor>\nmha_bwd(',
               'PYBIND11_MODULE(TORCH_EXTENSION_NAME, m) {']
    if any(api.count(anchor) != 1 for anchor in anchors):
        raise RuntimeError('Pinned source did not match the forward-only API boundaries')
    prefix_end, forward_start, forward_end, binding_start = [api.index(a) for a in anchors]
    if not prefix_end < forward_start < forward_end < binding_start:
        raise RuntimeError('Pinned source forward-only API boundaries were reordered')
    forward = _replace_once(api[forward_start:forward_end], '    run_mha_fwd(params);',
                            '    run_mha_fwd_<64, false>(params);', 'head64 direct dispatch')
    api = api[:prefix_end] + forward + api[binding_start:]
    api_path.write_text(api, encoding="utf-8")

    launch_path = source_dir / "csrc/flash_attn/src/flash_fwd_launch_template.h"
    launch = launch_path.read_text(encoding="utf-8")
    launch = _replace_once(
        launch, "#pragma once\n",
        "#pragma once\n#include <ATen/cuda/CUDAContext.h>\n"
        "#include <c10/cuda/CUDAException.h>\n", "stream/error-check includes",
    )
    launch = _replace_once(
        launch, "void run_flash_fwd(Flash_fwd_params &params) {\n",
        "void run_flash_fwd(Flash_fwd_params &params) {\n"
        "    const cudaStream_t stream = at::cuda::getCurrentCUDAStream();\n",
        "current PyTorch CUDA stream",
    )
    launch = _replace_once(
        launch,
        "        cudaFuncSetAttribute(flash_fwd_kernel<Kernel_traits, Is_causal, Is_even_MN>, "
        "cudaFuncAttributeMaxDynamicSharedMemorySize, maxbytes);",
        "        C10_CUDA_CHECK(cudaFuncSetAttribute("
        "flash_fwd_kernel<Kernel_traits, Is_causal, Is_even_MN>, "
        "cudaFuncAttributeMaxDynamicSharedMemorySize, maxbytes));",
        "shared-memory launch setup check",
    )
    launch = _replace_once(launch, "<<<dimGrid, dimBlock, maxbytes>>>",
                           "<<<dimGrid, dimBlock, maxbytes, stream>>>", "forward CUDA launch")
    launch = _replace_once(
        launch, "                                                                                    params.is_causal);\n    });",
        "                                                                                    params.is_causal);\n"
        "        C10_CUDA_KERNEL_LAUNCH_CHECK();\n    });", "forward launch error check",
    )
    launch_path.write_text(launch, encoding="utf-8")


def _stop_process_tree(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=10)


def _run(command, *, cwd=None, env=None, timeout=180, log_path=None):
    """Terminate the whole compiler tree on timeout; never leave a build running."""
    if log_path is None:
        return subprocess.run(command, cwd=cwd, env=env, check=True,
                              timeout=timeout, text=True, capture_output=True).stdout.strip()
    with Path(log_path).open("a", encoding="utf-8") as output:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=output,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _stop_process_tree(process)
            raise RuntimeError(f"T4 attention build exceeded {timeout}s; see {log_path}")
        except BaseException:
            # A notebook interrupt cancels the entire compiler tree before it
            # propagates; ordinary ComfyUI must not start beside orphan nvcc jobs.
            _stop_process_tree(process)
            raise
    if code:
        raise RuntimeError(f"T4 attention command failed ({code}); see {log_path}")
    return ""


def _host_available_bytes():
    available = 0
    for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
        if line.startswith("MemAvailable:"):
            available = int(line.split()[1]) * 1024
            break
    # A container can have much less memory than /proc/meminfo describes.
    for limit_path, usage_path in (
        ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory.current"),
        ("/sys/fs/cgroup/memory/memory.limit_in_bytes", "/sys/fs/cgroup/memory/memory.usage_in_bytes"),
    ):
        try:
            limit = Path(limit_path).read_text(encoding="ascii").strip()
            usage = Path(usage_path).read_text(encoding="ascii").strip()
            if limit != "max" and int(limit) > 0:
                available = min(available, max(0, int(limit) - int(usage)))
        except (OSError, ValueError):
            pass
    return available


def _validate_native(binary, env):
    # This source is executed only in the user's opt-in Colab session. A fresh
    # interpreter avoids stale loaded extensions and isolates its RNG state.
    program = f"""
import importlib.util
import json
import sys
import torch
import torch.nn.functional as F
spec = importlib.util.spec_from_file_location({T4_FLASH_MODULE!r}, sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert module.__phone_studio_patch__ == {T4_FLASH_PATCH!r}
assert module.__phone_studio_commit__ == {T4_FLASH_COMMIT!r}
assert callable(module.fwd)
assert torch.cuda.get_device_capability() == (7, 5)
assert torch.cuda.mem_get_info()[0] >= 64 * 1024 * 1024
stream = torch.cuda.Stream()
torch.manual_seed(10937)
cases = []
with torch.inference_mode(), torch.cuda.stream(stream):
    for query_length, key_length in ((128, 128), (128, 77), (129, 77)):
        q = torch.randn((1, query_length, 4, 64), device='cuda', dtype=torch.float16)
        k = torch.randn((1, key_length, 4, 64), device='cuda', dtype=torch.float16)
        v = torch.randn_like(k)
        output, lse = module.fwd(q, k, v, 0.125, False)
        reference = F.scaled_dot_product_attention(
            q.transpose(1, 2), k.transpose(1, 2), v.transpose(1, 2),
            dropout_p=0.0, is_causal=False).transpose(1, 2)
        stream.synchronize()
        assert output.shape == q.shape and output.dtype == q.dtype and output.device == q.device
        assert lse.shape == (1, 4, query_length)
        assert torch.isfinite(output).all().item() and torch.isfinite(lse).all().item()
        assert torch.allclose(output, reference, rtol=0.01, atol=0.002), 'Tiny numeric preflight failed'
        difference = (output.float() - reference.float()).abs()
        cases.append(dict(query_length=query_length, key_length=key_length, head_dim=64,
                          max_abs_error=difference.max().item(),
                          mean_abs_error=difference.mean().item()))
torch.cuda.synchronize()
print(json.dumps(dict(preflight_passed=True, preflight_cases=cases)))
"""
    try:
        result = json.loads(_run([sys.executable, "-c", program, str(binary)], env=env, timeout=60))
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or "No subprocess diagnostic")[-4000:]
        log_path = T4_FLASH_ROOT / "build.log"
        with log_path.open("a", encoding="utf-8") as output:
            output.write("\nTiny numeric/device/stream preflight failed:\n" + detail + "\n")
        raise RuntimeError(f"T4 attention tiny numeric/device/stream preflight failed; see {log_path}") from None
    if (not isinstance(result, dict) or result.get("preflight_passed") is not True or
            not isinstance(result.get("preflight_cases"), list) or
            len(result["preflight_cases"]) != 3):
        raise RuntimeError("T4 attention tiny preflight did not return valid results")
    return result


def _current_stamp(torch, env):
    if not T4_FLASH_STAMP.is_file() or T4_FLASH_STAMP.is_symlink():
        return None
    try:
        if T4_FLASH_STAMP.stat().st_size > 32 * 1024:
            return None
        stamp = json.loads(T4_FLASH_STAMP.read_text(encoding="utf-8"))
        if not isinstance(stamp, dict):
            return None
        expected = {
            "schema": 1, "commit": T4_FLASH_COMMIT, "patch": T4_FLASH_PATCH,
            "module": T4_FLASH_MODULE, "torch_version": str(torch.__version__),
            "torch_cuda": str(torch.version.cuda),
            "python_cache_tag": sys.implementation.cache_tag,
            "runtime_dir": str(T4_FLASH_RUNTIME),
            "preflight_passed": True,
        }
        if any(stamp.get(key) != value for key, value in expected.items()):
            return None
        binary = Path(stamp["module_file"])
        if (not binary.is_file() or binary.is_symlink() or
                binary.resolve().parent != T4_FLASH_RUNTIME.resolve() or
                not binary.name.startswith(T4_FLASH_MODULE + ".") or
                binary.suffix != ".so" or _sha256(binary) != stamp.get("module_sha256")):
            return None
        _validate_native(binary, env)
        return stamp
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError):
        return None


def install_t4_flash_attention(comfy_root=None, *, max_jobs=2, build_timeout_s=600,
                               reserve_disk_gb=8):
    """Build the optional isolated kernel; unsupported/failed installs return None.

    `comfy_root` is accepted for notebook callers but no ComfyUI source is changed.
    Compile concurrency is capped at two processes and build time at ten minutes.
    The caller should keep ordinary SDPA when this function returns None.
    """
    try:
        import torch

        if sys.platform != "linux" or not Path("/content").is_dir():
            raise RuntimeError("This optional installer requires a Linux Colab runtime")
        if not torch.cuda.is_available() or torch.cuda.get_device_capability() != (7, 5):
            raise RuntimeError("T4 attention requires an available SM7.5 CUDA GPU")
        if not torch.version.cuda or str(torch.version.cuda).split(".")[0] != "12":
            raise RuntimeError("Audited T4 source requires PyTorch CUDA12")
        if not shutil.which("git"):
            raise RuntimeError("git is unavailable")

        # All writes remain in an owned local directory, never Drive/site-packages.
        if T4_FLASH_ROOT.is_symlink() or (T4_FLASH_ROOT.exists() and
                T4_FLASH_ROOT.resolve() != Path("/content").resolve() / T4_FLASH_ROOT.name):
            raise RuntimeError("T4 attention installation directory is not an owned local path")
        T4_FLASH_ROOT.mkdir(parents=True, exist_ok=True)
        if T4_FLASH_RUNTIME.is_symlink():
            raise RuntimeError("T4 attention runtime directory must not be a symlink")
        env = dict(os.environ)
        stamp = _current_stamp(torch, env)
        if stamp is not None:
            print("[phone-studio-t4-flash] Reusing validated pinned forward kernel")
            return stamp

        nvcc = shutil.which("nvcc")
        if not nvcc:
            from torch.utils.cpp_extension import CUDA_HOME
            candidate = Path(CUDA_HOME or "/missing") / "bin/nvcc"
            nvcc = str(candidate) if candidate.is_file() else None
        if not nvcc:
            raise RuntimeError("CUDA12 nvcc is unavailable; existing CUDA packages are preserved")
        nvcc_output = _run([nvcc, "--version"], timeout=15)
        release = re.search(r"release\s+(\d+)\.(\d+)", nvcc_output)
        if release is None or release.group(1) != str(torch.version.cuda).split(".")[0]:
            raise RuntimeError("nvcc/PyTorch CUDA major versions differ")
        if _host_available_bytes() < 4 * _GIB:
            raise RuntimeError("Need at least 4GiB available host RAM to build T4 attention")
        reserve_disk_gb = max(0.0, float(reserve_disk_gb))
        if not reserve_disk_gb < 1024:
            raise RuntimeError("Invalid local disk reserve")
        if shutil.disk_usage(T4_FLASH_ROOT).free < (reserve_disk_gb + 2) * _GIB:
            raise RuntimeError(f"Need {reserve_disk_gb:g}GiB reserve plus 2GiB build scratch on local disk")

        # Reject any old stamp before attempting a replacement build.
        T4_FLASH_STAMP.unlink(missing_ok=True)
        max_jobs = min(2, max(1, int(max_jobs)))
        build_timeout_s = min(600, max(60, int(build_timeout_s)))
        env["MAX_JOBS"] = str(max_jobs)
        env["TORCH_CUDA_ARCH_LIST"] = "7.5"
        env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        log_path = T4_FLASH_ROOT / "build.log"
        log_path.write_text(f"Pinned source {T4_FLASH_COMMIT}; patch {T4_FLASH_PATCH}\n",
                            encoding="utf-8")
        print(f"[phone-studio-t4-flash] Building optional T4 kernel; max {max_jobs} jobs, "
              f"{build_timeout_s}s build limit. Log: {log_path}")

        # Missing build helpers are isolated too; do not install requirements.txt.
        dependency_specs = {
            "ninja": "ninja>=1.11,<2", "wheel": "wheel>=0.40,<1",
            "setuptools": "setuptools>=64,<81",
        }
        missing = [spec for name, spec in dependency_specs.items()
                   if importlib.util.find_spec(name) is None]
        if missing:
            deps = T4_FLASH_ROOT / "build_deps"
            if deps.is_symlink():
                raise RuntimeError("T4 attention build-dependency directory must not be a symlink")
            _run([sys.executable, "-m", "pip", "install", "--no-deps", "--no-input",
                  "--target", str(deps), *missing], env=env, timeout=120, log_path=log_path)
            env["PYTHONPATH"] = str(deps) + os.pathsep + env.get("PYTHONPATH", "")
            env["PATH"] = str(deps / "bin") + os.pathsep + env.get("PATH", "")

        with tempfile.TemporaryDirectory(prefix="build-", dir=T4_FLASH_ROOT) as scratch:
            source_dir = Path(scratch) / "source"
            candidate_runtime = Path(scratch) / "runtime"
            source_dir.mkdir()
            _run(["git", "init", "--quiet"], cwd=source_dir, timeout=30)
            _run(["git", "remote", "add", "origin",
                  "https://github.com/ssiu/flash-attention-turing.git"], cwd=source_dir)
            _run(["git", "-c", "core.autocrlf=false", "fetch", "--depth", "1",
                  "origin", T4_FLASH_COMMIT], cwd=source_dir, timeout=120, log_path=log_path)
            _run(["git", "-c", "core.autocrlf=false", "checkout", "--detach", "FETCH_HEAD"],
                 cwd=source_dir, timeout=60, log_path=log_path)
            if _run(["git", "rev-parse", "HEAD"], cwd=source_dir) != T4_FLASH_COMMIT:
                raise RuntimeError("T4 source revision mismatch")
            _run(["git", "submodule", "update", "--init", "--depth", "1", "csrc/cutlass"],
                 cwd=source_dir, timeout=180, log_path=log_path)
            if _run(["git", "rev-parse", "HEAD"], cwd=source_dir / "csrc/cutlass") != T4_FLASH_CUTLASS_COMMIT:
                raise RuntimeError("CUTLASS submodule revision mismatch")
            _patch_source(source_dir)
            _run([sys.executable, "-m", "pip", "install", "--no-deps", "--no-build-isolation",
                  "--no-input", "--no-cache-dir", "--target", str(candidate_runtime), str(source_dir)],
                 env=env, timeout=build_timeout_s, log_path=log_path)
            binaries = list(candidate_runtime.glob(T4_FLASH_MODULE + ".*.so"))
            if len(binaries) != 1 or binaries[0].is_symlink():
                raise RuntimeError("Isolated T4 build did not produce exactly one native module")
            preflight = _validate_native(binaries[0], env)
            if T4_FLASH_RUNTIME.exists():
                # The only removal is this fixed, verified, installer-owned local path.
                if T4_FLASH_RUNTIME.resolve() != T4_FLASH_ROOT.resolve() / "runtime":
                    raise RuntimeError("Refusing to replace an unowned runtime directory")
                shutil.rmtree(T4_FLASH_RUNTIME)
            candidate_runtime.rename(T4_FLASH_RUNTIME)

        binary = next(T4_FLASH_RUNTIME.glob(T4_FLASH_MODULE + ".*.so"))
        stamp = {
            "schema": 1, "commit": T4_FLASH_COMMIT, "patch": T4_FLASH_PATCH,
            "module": T4_FLASH_MODULE, "torch_version": str(torch.__version__),
            "torch_cuda": str(torch.version.cuda),
            "python_cache_tag": sys.implementation.cache_tag,
            "runtime_dir": str(T4_FLASH_RUNTIME), "module_file": str(binary),
            "module_sha256": _sha256(binary), "nvcc_release": release.group(0),
            "preflight_passed": True,
            "preflight_cases": preflight["preflight_cases"],
            "built_at_unix": int(time.time()),
        }
        temporary_stamp = T4_FLASH_ROOT / "install.json.part"
        temporary_stamp.write_text(json.dumps(stamp, indent=2) + "\n", encoding="utf-8")
        temporary_stamp.replace(T4_FLASH_STAMP)
        print("[phone-studio-t4-flash] Validated pinned forward kernel ready; "
              "speed/quality remain unmeasured")
        return stamp
    except Exception as error:
        print(f"[phone-studio-t4-flash] Optional kernel unavailable: {type(error).__name__}: {error}. "
              "Keeping ordinary PyTorch attention.")
        return None
