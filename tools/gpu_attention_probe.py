"""User-run SDXL attention diagnostic using Colab's existing PyTorch.

Run this in a fresh GPU runtime BEFORE starting ComfyUI or loading a model:
    python tools/gpu_attention_probe.py
Use --batch-size 1 if ComfyUI splits positive/negative conditioning for memory.
Use --t4-flash to compare an already-built, installer-validated private T4 kernel;
this flag never installs anything or imports ComfyUI. The opt-in comparison also
times contiguous B,H,L,D inputs that require actual conversion copies. The
original BLHD-backed view can convert back to BLHD without allocating a copy.
This script has not been executed here. Its times concern attention on synthetic
tensors, not denoising or phone-to-image latency. It neither installs packages
nor changes ComfyUI, precision flags, models, steps, or resolution.

The six cases approximate SDXL at 768x1024: its 96x128 latent is downsampled
to 48x64 (3072 tokens, 10 heads) and 24x32 (768 tokens, 20 heads), head width
64. Cross-attention uses representative 77/154-token conditioning; an actual
prompt can differ. Batch 2 approximates batched positive/negative conditioning.
Inputs start in B,L,H,D layout and are transposed to ComfyUI's SDPA B,H,L,D
layout, preserving the strides rather than benchmarking different storage.

Primary sources inspected on 2026-09-30:
https://raw.githubusercontent.com/Comfy-Org/ComfyUI/master/comfy/model_detection.py
https://raw.githubusercontent.com/Comfy-Org/ComfyUI/master/comfy/ldm/modules/attention.py
https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/raw/main/unet/config.json
https://docs.pytorch.org/docs/2.14/generated/torch.nn.functional.scaled_dot_product_attention.html
https://github.com/ssiu/flash-attention-turing/tree/9ef98fcb506bb1e2fe3cece50935e2935bf6b124

Default SDPA is compared with forced EFFICIENT_ATTENTION where the installed
PyTorch supports the public context manager. Unsupported kernels are reported,
never replaced by a math-only run. The default profiler pass identifies selected
operators and, where available, CUDA kernel names. Floating-point differences
between attention kernels are possible; numeric comparisons are not image QA.
Output is one JSON object per line. No app credentials or prompts are accessed.
"""

import argparse
import gc
import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import statistics
import sys


def emit(kind, **fields):
    print(json.dumps({"kind": kind, **fields}, allow_nan=False), flush=True)


def error_text(exc):
    return f"{type(exc).__name__}: {exc}"[:1000]


def package_version(name):
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def measure(torch, call, warmups=3, repeats=10):
    out = None
    for _ in range(warmups):
        out = call()
    torch.cuda.synchronize()
    start = torch.cuda.Event(enable_timing=True)
    end = torch.cuda.Event(enable_timing=True)
    samples = []
    for _ in range(repeats):
        start.record()
        out = call()
        end.record()
        end.synchronize()
        samples.append(float(start.elapsed_time(end)))
    return out, {
        "warmups": warmups,
        "repeats": repeats,
        "median_ms": statistics.median(samples),
        "min_ms": min(samples),
        "max_ms": max(samples),
    }


def profile_default(torch, call):
    profiler = getattr(torch, "profiler", None)
    if profiler is None or not hasattr(profiler, "profile"):
        return {"available": False, "reason": "torch.profiler unavailable"}
    activity = getattr(profiler, "ProfilerActivity", None)
    if activity is None:
        return {"available": False, "reason": "ProfilerActivity unavailable"}
    activities = [activity.CPU]
    supported = getattr(profiler, "supported_activities", None)
    cuda_activity = getattr(activity, "CUDA", None)
    cuda_enabled = False
    if supported is not None and cuda_activity in supported():
        activities.append(cuda_activity)
        cuda_enabled = True
    with profiler.profile(activities=activities) as trace:
        call()
        torch.cuda.synchronize()
    operators = sorted({
        event.key for event in trace.key_averages()
        if "attention" in event.key.lower()
    })
    kernels = sorted({
        event.name[:300] for event in trace.events()
        if "cuda" in str(getattr(event, "device_type", "")).lower()
    })
    return {
        "available": True,
        "cuda_trace_enabled": cuda_enabled,
        "attention_operators": operators[:16],
        "cuda_kernel_names": kernels[:16],
        "note": "One untimed default-SDPA pass; profiler overhead excluded from timings.",
    }


def numeric_difference(torch, default, efficient):
    if not bool(torch.isfinite(default).all()) or not bool(torch.isfinite(efficient).all()):
        return {"finite": False, "max_abs": None, "mean_abs": None, "relative_rms": None}
    reference = default.float()
    difference = efficient.float() - reference
    denominator = float(reference.square().mean().sqrt())
    return {
        "finite": True,
        "max_abs": float(difference.abs().max()),
        "mean_abs": float(difference.abs().mean()),
        "relative_rms": float(difference.square().mean().sqrt()) / max(denominator, 1e-12),
    }


def load_validated_t4_native(torch, device):
    """Accept only the isolated, pinned/patched kernel from our user-run installer."""
    commit = "9ef98fcb506bb1e2fe3cece50935e2935bf6b124"
    patch = "phone-studio-t4-forward-v1"
    module_name = "phone_studio_flash_attn_turing"
    root = Path("/content/phone_studio_t4_flash")
    runtime = root / "runtime"
    manifest_path = root / "install.json"
    if (torch.cuda.get_device_capability(device) != (7, 5)
            or str(torch.version.cuda).split(".")[0] != "12"):
        raise RuntimeError("Optional T4 kernel requires SM7.5 and PyTorch CUDA12")
    if (root.is_symlink() or runtime.is_symlink() or manifest_path.is_symlink()
            or not manifest_path.is_file() or manifest_path.stat().st_size > 32768):
        raise RuntimeError("Matching local T4 installer manifest is unavailable")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    identity = {
        "schema": 1, "commit": commit, "patch": patch, "module": module_name,
        "torch_version": str(torch.__version__), "torch_cuda": str(torch.version.cuda),
        "python_cache_tag": sys.implementation.cache_tag, "runtime_dir": str(runtime),
        "preflight_passed": True,
    }
    if (not isinstance(manifest, dict)
            or manifest.get("preflight_passed") is not True
            or any(manifest.get(key) != value for key, value in identity.items())):
        raise RuntimeError("T4 installer manifest does not match this runtime/build")
    binary = Path(manifest.get("module_file", ""))
    if (not binary.is_absolute() or binary.is_symlink() or binary.parent != runtime
            or binary.resolve().parent != runtime.resolve() or not binary.is_file()
            or not binary.name.startswith(module_name + ".") or binary.suffix != ".so"):
        raise RuntimeError("T4 installer native module path is invalid")
    digest = hashlib.sha256()
    with binary.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != manifest.get("module_sha256"):
        raise RuntimeError("T4 installer native module hash has changed")
    module = sys.modules.get(module_name)
    if module is None:
        spec = importlib.util.spec_from_file_location(module_name, str(binary))
        if spec is None or spec.loader is None:
            raise RuntimeError("T4 native module loader is unavailable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sys.modules[module_name] = module
    if (getattr(module, "__phone_studio_commit__", None) != commit
            or getattr(module, "__phone_studio_patch__", None) != patch
            or Path(getattr(module, "__file__", "")).resolve() != binary.resolve()
            or not callable(getattr(module, "fwd", None))):
        raise RuntimeError("T4 native module identity/API does not match")
    return module, manifest


def t4_forward(torch, module, q, k, v):
    """Measure the real B,H,L,D -> contiguous B,L,H,D -> B,H,L,D path."""
    tensors = (q, k, v)
    if (torch.is_grad_enabled()
            or torch.cuda.get_device_capability(q.device) != (7, 5)
            or any(type(tensor) is not torch.Tensor or tensor.ndim != 4
                   or not tensor.is_cuda or tensor.dtype != torch.float16
                   or tensor.layout != torch.strided or tensor.requires_grad
                   or tensor.device != q.device for tensor in tensors)
            or not 1 <= q.shape[0] <= 4 or not 1 <= q.shape[1] <= 64
            or any(tensor.shape[0] != q.shape[0] or tensor.shape[1] != q.shape[1]
                   or tensor.shape[3] != 64 or not 1 <= tensor.shape[2] <= 16384
                   for tensor in tensors)
            or k.shape[2] != v.shape[2]
            or sum(tensor.numel() * tensor.element_size() for tensor in tensors) > 128 * 2**20):
        raise RuntimeError("Synthetic case exceeds the optional T4 adapter's supported bounds")
    q_blhd, k_blhd, v_blhd = [tensor.transpose(1, 2).contiguous() for tensor in tensors]
    if any(tensor.data_ptr() % 16 for tensor in (q_blhd, k_blhd, v_blhd)):
        raise RuntimeError("T4 contiguous tensors do not meet 16-byte alignment")
    output, _ = module.fwd(q_blhd, k_blhd, v_blhd, 0.125, False)
    if output.shape != q_blhd.shape or output.dtype != q.dtype or output.device != q.device:
        raise RuntimeError("T4 kernel returned an unexpected tensor")
    return output.transpose(1, 2)


def compare_t4(torch, functional, module, q, k, v, default, default_timing):
    output, timing = measure(torch, lambda: t4_forward(torch, module, q, k, v))
    difference = numeric_difference(torch, default, output)
    if not difference["finite"]:
        raise RuntimeError("T4 numeric comparison contains non-finite values")
    timing.update(
        speedup_vs_default=default_timing["median_ms"] / max(timing["median_ms"], 1e-12),
        difference_from_default=difference,
        includes_layout_conversion=True,
        conversion_allocates=any(not tensor.transpose(1, 2).is_contiguous() for tensor in (q, k, v)),
    )
    # A second layout keeps identical values but requires BLHD conversion copies.
    # Baseline SDPA and T4 both receive those same contiguous B,H,L,D inputs.
    copied_q, copied_k, copied_v = [tensor.contiguous() for tensor in (q, k, v)]
    copied_call = lambda: functional.scaled_dot_product_attention(
        copied_q, copied_k, copied_v, attn_mask=None, dropout_p=0.0, is_causal=False,
    )
    copied_default, copied_default_timing = measure(torch, copied_call)
    copied_output, copied_timing = measure(
        torch, lambda: t4_forward(torch, module, copied_q, copied_k, copied_v),
    )
    copied_difference = numeric_difference(torch, copied_default, copied_output)
    if not copied_difference["finite"]:
        raise RuntimeError("Copied-layout T4 numeric comparison contains non-finite values")
    copied_timing["speedup_vs_default"] = (
        copied_default_timing["median_ms"] / max(copied_timing["median_ms"], 1e-12))
    copied = {
        "input_layout": "contiguous B,H,L,D",
        "q_stride": list(copied_q.stride()),
        "includes_layout_conversion": True,
        "conversion_allocates": any(not tensor.transpose(1, 2).is_contiguous()
                                    for tensor in (copied_q, copied_k, copied_v)),
        "default_sdpa": copied_default_timing,
        "t4_flash": copied_timing,
        "difference_from_default": copied_difference,
    }
    return timing, copied


class NativeProbeFailure(Exception):
    """Do not attempt another CUDA case after a native probe failure."""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, choices=(1, 2), default=2)
    parser.add_argument("--no-profile", action="store_true", help="Skip kernel profiling.")
    parser.add_argument("--t4-flash", action="store_true",
                        help="Compare an already-built, validated private T4 kernel; never install.")
    options = parser.parse_args()
    try:
        import torch
        import torch.nn.functional as functional
    except Exception as exc:
        emit("error", stage="import", error=error_text(exc))
        return 1
    if not torch.cuda.is_available():
        emit("error", stage="runtime", error="CUDA GPU unavailable. Select a GPU Colab runtime.")
        return 1
    try:
        properties = torch.cuda.get_device_properties(0)
        device = torch.device("cuda:0")
        torch.cuda.set_device(device)
        free, total = torch.cuda.mem_get_info(device)
        emit(
            "runtime",
            gpu=properties.name,
            compute_capability=f"{properties.major}.{properties.minor}",
            torch_version=str(torch.__version__),
            torch_cuda_version=torch.version.cuda,
            cudnn_version=torch.backends.cudnn.version(),
            compiled_cuda_architectures=torch.cuda.get_arch_list(),
            xformers_version=package_version("xformers"),
            free_vram_mib=round(free / 2**20, 1),
            total_vram_mib=round(total / 2**20, 1),
            flash_sdp_enabled=torch.backends.cuda.flash_sdp_enabled(),
            efficient_sdp_enabled=torch.backends.cuda.mem_efficient_sdp_enabled(),
            math_sdp_enabled=torch.backends.cuda.math_sdp_enabled(),
            batch_size=options.batch_size,
            scope="Synthetic SDXL attention microbenchmark; no model or app timing.",
        )
    except Exception as exc:
        emit("error", stage="runtime_metadata", error=error_text(exc))
        return 1
    efficient_context = None
    try:
        from torch.nn.attention import SDPBackend, sdpa_kernel
        efficient_context = lambda: sdpa_kernel(backends=[SDPBackend.EFFICIENT_ATTENTION])
    except (ImportError, AttributeError):
        emit("notice", message="Public efficient-only context unavailable; default SDPA remains available.")

    t4_module = None
    if options.t4_flash:
        try:
            t4_module, t4_manifest = load_validated_t4_native(torch, device)
            emit("notice", feature="t4_flash", available=True,
                 source_commit=t4_manifest["commit"], patch=t4_manifest["patch"],
                 message="Validated private kernel loaded. Original and copied-layout timings include conversion; no image QA.")
        except Exception as exc:
            emit("notice", feature="t4_flash", available=False, error=error_text(exc),
                 message="Optional T4 comparison skipped; this probe never installs packages.")

    cases = [
        ("level_640_self", 10, 3072, 3072),
        ("level_640_cross_77", 10, 3072, 77),
        ("level_640_cross_154", 10, 3072, 154),
        ("level_1280_self", 20, 768, 768),
        ("level_1280_cross_77", 20, 768, 77),
        ("level_1280_cross_154", 20, 768, 154),
    ]
    generator = torch.Generator(device=device).manual_seed(730)
    with torch.inference_mode():
        for name, heads, query_length, key_length in cases:
            q = k = v = default = efficient = call = None
            fatal_native = False
            result = {
                "name": name, "batch": options.batch_size, "heads": heads,
                "query_length": query_length, "key_length": key_length,
                "head_dim": 64, "dtype": "float16", "mask": None, "causal": False,
            }
            try:
                free, _ = torch.cuda.mem_get_info(device)
                if free < 2 * 2**30:
                    emit("case", **result, skipped="Less than 2 GiB free; run before model loading.")
                    continue
                torch.cuda.reset_peak_memory_stats(device)
                baseline = torch.cuda.memory_allocated(device)

                def tensor(length):
                    return torch.randn(
                        options.batch_size, length, heads, 64,
                        device=device, dtype=torch.float16, generator=generator,
                    ).transpose(1, 2)

                q, k, v = tensor(query_length), tensor(key_length), tensor(key_length)
                result["q_stride"] = list(q.stride())
                call = lambda: functional.scaled_dot_product_attention(
                    q, k, v, attn_mask=None, dropout_p=0.0, is_causal=False,
                )
                default, result["default_sdpa"] = measure(torch, call)
                if not options.no_profile:
                    try:
                        result["default_profile"] = profile_default(torch, call)
                    except Exception as exc:
                        result["default_profile"] = {"available": False, "error": error_text(exc)}
                if efficient_context is not None:
                    try:
                        with efficient_context():
                            efficient, result["efficient_only"] = measure(torch, call)
                        result["difference_from_default"] = numeric_difference(torch, default, efficient)
                    except Exception as exc:
                        result["efficient_only"] = {"error": error_text(exc)}
                if t4_module is not None:
                    if torch.cuda.mem_get_info(device)[0] < 2 * 2**30:
                        result["t4_flash"] = {"skipped": "Less than 2 GiB free before optional comparison."}
                    else:
                        try:
                            result["t4_flash"], result["t4_flash_copy_layout"] = compare_t4(
                                torch, functional, t4_module, q, k, v,
                                default, result["default_sdpa"],
                            )
                        except Exception as exc:
                            fatal_native = True
                            raise NativeProbeFailure(error_text(exc)) from exc
                result["case_peak_extra_allocated_mib"] = round(
                    max(0, torch.cuda.max_memory_allocated(device) - baseline) / 2**20, 2,
                )
                result["case_peak_reserved_mib"] = round(torch.cuda.max_memory_reserved(device) / 2**20, 2)
                result["free_vram_after_mib"] = round(torch.cuda.mem_get_info(device)[0] / 2**20, 1)
                emit("case", **result)
            except NativeProbeFailure as exc:
                emit("error", stage="t4_flash", **result, error=error_text(exc),
                     message="Probe stopped after native failure; restart the runtime before further GPU work.")
                return 1
            except Exception as exc:
                emit("case", **result, error=error_text(exc))
            finally:
                q = k = v = default = efficient = call = None
                gc.collect()
                if not fatal_native:
                    torch.cuda.empty_cache()
    emit("complete", message="Send all JSON lines. Kernel timing is not image-generation speed or image-quality validation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
