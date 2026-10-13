> Router stage (0.2): new phone jobs use one router, which fans out to the workers and adds optional prompt assistance, durable collection and visual review. Worker speed research below remains relevant; direct-phone fan-out descriptions refer to the preceding version. Editing bypasses incompatible per-render hooks. See [current setup](ROUTER_GUIDE.md) and [verification](VERIFICATION.md).

# Two presets and backend speed tuning

The phone has one standard workflow and two presets: **Balanced, 24 steps (default)** and **Fast, 18 steps**. Both use CFG 6.5, `dpmpp_2m`/`karras`, your checkpoint, canvas, prompts and optional style LoRA. Fast requests 25% fewer steps; that is not a measured elapsed-time saving. The debug APK build, 31 local unit tests, lint and 27 source checks passed; [verification scope](VERIFICATION.md). The notebook, phone app and native GPU installer were not executed.

Following the latest speed-first instruction, all implemented speed experiments are **requested on by default where supported**. These defaults can change images, and FP16 VAE/accumulation can produce invalid output. Balanced retains its recipe, but does not promise the old default's pixels. No checkpoint is substituted and no paid dependency was added. Timing stays off because synchronization slows normal use; VRAM stays `auto` because high/legacy modes are mutually exclusive and full residency can exceed a T4's memory.

## Saved phone switch

Create's **Extra acceleration** switch defaults on and is saved with the draft and newly generated image records. For each newly submitted image it controls EasyCache, the guarded T4 attention hook, fast lossless PNG, and eligible conditioning caching. It leaves already accepted jobs alone. Toggling it changes stock sampler/save cache fingerprints so the same seed cannot simply return an image computed with the other switch position; model and text caches remain reusable.

**Launch-time settings remain separate:** FP16 accumulation/intermediates/VAE, supported-GPU compilation and newer-GPU attention selection require notebook changes and a restart. The phone switch does not reset them. Turning it off is therefore not an original-quality baseline by itself.

**Both sides must be updated for the switch:** `ComfyApi.kt`/`BackendRunner.kt` add optional Boolean `extra_data.phone_studio_speed_extras` to the ordinary `/prompt` request; notebook bridge execution/save/attention hooks read it. The existing health response adds `speedExtrasSupported`. Old apps omit the flag and get notebook defaults; old notebooks ignore the extra field, so their acceleration cannot be switched remotely. An incompatible updated executor rejects an explicit switch with a clear error. No endpoint or existing request/image field was removed.

Verify: submit the same seed once with the switch on and once off; confirm a new sampling stage and the expected EasyCache/PNG metadata for each. Reopen the app and confirm the switch remains selected. Rebuild/install the app and rerun notebook settings/bridge/launch cells to obtain both sides.

## Defaults, estimates and tradeoffs

All benefits below are source estimates, not benchmarks. Requested settings can be skipped by hardware/API/resource guards.

| Notebook option | Default | Estimated benefit | Tradeoff / eligibility |
| --- | --- | --- | --- |
| `LOCAL_MODEL_CACHE` | True, 24 GiB cap / 8 GiB reserve | Avoid repeated large weight reads from Drive | First copy and runtime reset still cost time; no extra GPU replica. |
| `MODEL_CATALOG_CACHE_SECONDS` | 300 | Avoid render-time recursive Drive scans | Connect/Refresh remain fresh; direct Drive edits need Refresh. |
| `LOCAL_OUTPUT_CACHE` | True, 256 MiB cap | Avoid small Drive encoding writes/scans and recent-image Drive reads | Identical durable copy still finishes before success. |
| `COMPRESS_JSON_RESPONSES` | True if supported | Reduce metadata transfer | Small compression CPU cost; PNG unchanged. |
| `FAST_PNG_COMPRESSION` | True | Possibly shorter lossless encoding | Larger PNGs may offset savings during copy/download. |
| `FAST_DENOISE_CACHE` | True | Skip some full diffusion evaluations | EasyCache approximates model output; actual benefit/quality unknown. |
| `FAST_T4_FLASH_ATTENTION` | True if validated on SM7.5 | Possibly shorter eligible SDXL attention | Native build adds startup time; arithmetic can change pixels. |
| `FAST_CONDITIONING_CACHE` | True, lower priority | Possibly avoid repeated conditioning concatenation/transfers | Skips when EasyCache is requested or the validated T4 hook is enabled; bounded 8 MiB cache, strict ordinary SDXL/T4 guard. |
| `FAST_FP16_ACCUMULATION` | True if supported | Possibly faster eligible GEMMs | Lower numerical precision and overflow risk. |
| `FAST_FP16_INTERMEDIATES` | True if supported | Smaller selected CPU boundary buffers | Noise/RGB rounding changes; sampler still uses internal FP32. |
| `FAST_FP16_VAE` | True if supported | Possibly faster decode with less decoder memory | Some SDXL VAEs produce black/non-finite images. |
| `CHANNELS_LAST` / autotune | True | Existing convolution tuning | First use has tuning cost; unfamiliar architectures need review. |
| `PHONE_STUDIO_AUTO_COMPILE` secret | Defaults 1 on supported newer GPUs; forced 0 on T4 | Possible warm inference saving | Compilation adds first-use cost; not supported on this T4 path. |
| `VRAM_MODE` | `auto` | Retain memory management suited to available memory | `legacy` and `high` are manual alternatives, not additional on/off accelerators. |
| `PHONE_STUDIO_TIMING` | False | Diagnostic only | GPU synchronization perturbs normal throughput. |

Negotiated gzip uses stock ComfyUI JSON/text middleware and OkHttp decoding. Verify `/history` with gzip acceptance, checking `Content-Encoding` and unchanged decoded JSON; set `COMPRESS_JSON_RESPONSES = False` and restart to revert. [ComfyUI middleware](https://github.com/Comfy-Org/ComfyUI/blob/master/server.py), [OkHttp decoding](https://github.com/square/okhttp/blob/parent-4.12.0/okhttp/src/main/kotlin/okhttp3/internal/http/BridgeInterceptor.kt)

## Reuse confirmed startup warm-up

The startup preview now matches the phone's 768 × 1024/default sampler. Instance-bound `completedWarmup` health metadata is published only after successful history and decoded preview output. The phone avoids a duplicate connection preview for matching checkpoint/shape/sampler/scheduler, CFG greater than 1 and no LoRA. Subsequent submissions invalidate the proof. Old versions retain ordinary phone warm-up. One in-flight app preview per backend prevents overlapping connection checks from duplicating it.

When a phone preview is needed, its fixed CFG-1 graph shares positive conditioning with the required negative socket and omits unused negative encoding. Both real presets retain separate positive/negative encoders. Estimated saving: one encoding pass on a miss, possibly negligible with cached CLIP. [ComfyUI CFG-1 optimization](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/samplers.py)

Both sides: notebook settings/bridge/launch and Android `ComfyApi.kt`/`StudioViewModel.kt`. Verify: connect with matching defaults before rendering and confirm no second sampling/preview pair; change shape and confirm a six-node phone preview still runs. Other phone previews record acceptance rather than confirmed completion, an existing limitation.

## Local output cache

The stock SaveImage encoder writes locally, copies completed PNG bytes to Drive, then returns the normal filename/subfolder/type descriptor. Recent ordinary `/view` reads use identical cached bytes; older/special requests use Drive. Unique nested folders avoid filename collisions after eviction/restart. Cache cleanup never deletes Drive originals. A failed durable copy fails generation.

Verify: generate, find the descriptor's file on Drive, then load it after disabling the cache/restarting. Compare `save_png_local`, `save_png_drive_copy` and phone image-ready timing. Revert: `LOCAL_OUTPUT_CACHE = False`, rerun settings/bridge and restart. This cannot remove durable-copy or download time.

## Fast lossless PNG

`FAST_PNG_COMPRESSION = True` uses level 1 instead of stock level 4 for exact ordinary `PhoneStudio` saves with Extra acceleration on. Standard float-to-8-bit conversion and PNG metadata remain; decoded pixels are unchanged by compression alone. Previews/nonstandard savers use their original path. [ComfyUI saver](https://github.com/Comfy-Org/ComfyUI/blob/master/nodes.py), [Pillow PNG options](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#png)

Verify: inspect `phone_studio_png_encoding` for level 1 and compare encoding, Drive-copy, encoded bytes and phone image-ready duration with the phone switch off. Estimated overall benefit is unknown because larger files can slow transfer. Revert independently: set False, rerun settings/bridge and restart. The draft/image record saves the phone switch, not all notebook flags; the PNG encoding record identifies the actual compression.

## Fast denoise cache

With `FAST_DENOISE_CACHE = True` and Extra acceleration on, the bridge inserts stock ComfyUI EasyCache into app render graphs with a request ID: threshold 0.2, start 0.15, end 0.95. Warm-ups/unrelated graphs remain untouched. Requested checkpoint/LoRA/steps/sampler/size remain, but some denoising evaluations are approximated. Missing EasyCache support reports an error rather than pretending to accelerate. [Upstream implementation](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_extras/nodes_easycache.py)

Verify: check the log and saved PNG graph for EasyCache, then compare images and synchronized sampling against Extra acceleration off. A skipped-step ratio is not an elapsed-time speedup. Revert independently: set `FAST_DENOISE_CACHE = False`, rerun settings/bridge and restart. Exact reproduction also needs matching notebook flags/runtime, not just the saved phone switch.

## Fast T4 FlashAttention

`FAST_T4_FLASH_ATTENTION = True` requests the embedded pinned installer and per-model SDXL adapter. Extra acceleration off bypasses native dispatch per image without unloading weights. Eligible calls require validated Linux/CUDA12 SM7.5, unmasked FP16 on one GPU, head width 64 and ordinary bounded SDXL shapes. Existing preferred/quantized attention/overrides are preserved. Unsupported setup/calls retain SDPA; native CUDA failures propagate, requiring a restart rather than retry on a potentially invalid context.

The private build pins [the Turing implementation](https://github.com/ssiu/flash-attention-turing/tree/9ef98fcb506bb1e2fe3cece50935e2935bf6b124), verifies source/binary/runtime identity and patches current CUDA stream/device checks. It does not replace PyTorch/CUDA or install a global attention package. Compilation is capped at two jobs and 600 seconds, with at least 4 GiB available host RAM and 2 GiB scratch above the 8 GiB disk reserve; downloads/preflight add time. Compatibility/completion on free Colab are unverified.

Three tiny numeric/current-stream checks run when you run the settings cell. They do not prove large-shape correctness, final-image quality or speed; none ran here. Manifest/build log: `/content/phone_studio_t4_flash/install.json` and `build.log`.

Verify: confirm validated build, hook-enabled and first-use logs, then compare sampling/total time and matching-seed images against False with other experiments off. Revert: set False, rerun settings/bridge and restart; restart the runtime after native failures. The pinned helper and embedded notebook copy must be changed together.

Optional synthetic probe, after a successful settings-cell build and before starting ComfyUI: upload `tools/gpu_attention_probe.py` and run `!python /content/gpu_attention_probe.py --t4-flash --no-profile`. It installs/builds nothing and loads only the validated binary. JSON separates original and copied layouts, including conversion cost/numeric differences; it is not a full-image benchmark or a prerequisite for using these changes.

## Fast conditioning cache

`FAST_CONDITIONING_CACHE = True` requests a scoped concatenation/transfer cache only for eligible ordinary SDXL/T4 FP16, batch-1 Balanced/Fast renders. EasyCache and validated T4 attention take precedence: conditioning setup skips when EasyCache is requested or the validated T4 hook is enabled. With EasyCache off and a failed T4 build, conditioning may still be eligible. Disable both flags and restart for a standalone comparison. The phone switch then gates it per render.

The shared-weight model hook uses private prompt snapshots and device/dtype/layout/stream keys, caps retained snapshots and GPU tensors together at 8 MiB/four layouts, and restores conditioning/releases tensors in `finally`. Custom conditioning, overrides, compilation and unsupported configurations are declined. It does not cache K/V projections or patch global tensor functions. Extra VRAM can affect offloading, so net benefit may be small or negative.

Verify: confirm eligibility/skip logs and `Conditioning cache released` hits/misses/cap, then compare images and synchronized sampling with False. Revert: set `FAST_CONDITIONING_CACHE = False`, rerun settings/bridge and restart. This experiment has no measured speed or validated image-equivalence result.

## Fast precision experiments

The three stock precision flags are requested True where CLI/PyTorch support exists; unsupported features print a skip and retain stock precision. They require a notebook restart and are not controlled by the phone switch. No new dependency is needed. Compare each separately, with all other experiments off. [Dtype selection](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/model_management.py), [VAE output](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/sd.py), [noise construction](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/sample.py), [sampling casts](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/samplers.py)

| Flag | Scope / estimate | One-line verification |
| --- | --- | --- |
| `FAST_FP16_ACCUMULATION` | Lower precision eligible GEMMs; unknown speed gain, overflow possible. Uses named feature beside autotune, never bare broad `--fast`. | Confirm startup accumulation log and compare synchronized sampling/total time plus images against False. |
| `FAST_FP16_INTERMEDIATES` | Selected CPU boundary buffers/noise/RGB rounding, not all internal denoiser tensors; portrait RGB is calculated 4.5 MiB versus 9 MiB. | Confirm startup precision log and compare decode/total time and matching-seed PNGs against False. |
| `FAST_FP16_VAE` | Forced lower precision decode; ordinary inspected SDXL/T4 baseline appears FP32. | Confirm actual VAE dtype and compare decode/total plus images; black/non-finite output fails the comparison. |

Revert any independently: set False, rerun settings and restart. Backend flags/runtime must be recorded separately for reproduction.

## Comparison to run

Build/install the updated app using README instructions. Enable notebook `PHONE_STUDIO_TIMING = True`, rerun settings/bridge and restart. Keep one backend, fixed model/LoRA strength/prompt/canvas and a visible Create result card. Record cold startup/first render separately, then three distinct seeds (1001/1002/1003); reuse that sequence between modes, not repeatedly within one mode. Confirm each has a sampling log.

For an original-settings baseline use Balanced, Extra acceleration off, all notebook `FAST_*` flags False, `PHONE_STUDIO_AUTO_COMPILE=0` and `VRAM_MODE='auto'`, then restart. Keep quality-neutral model/catalog/local-output caches and gzip on. On T4 this retains the original SDPA path. On a newer GPU, explicitly retain the original attention choice as well.

Then compare one change at a time: local output cache, EasyCache, T4 attention, each precision flag, PNG level, standalone conditioning, and Balanced versus Fast. The normal requested-all-on combination deserves its own final image/total-time comparison; isolated gains need not add together. Restore timing False for everyday use and separately measure unsynchronized throughput.

Send back later: GPU/VRAM/compute capability, Torch/CUDA/ComfyUI revision, notebook flags, seeds, `[phone-studio-timing]` lines and matching Android `PhoneStudioTiming` lines, plus first-use/skip/errors and visual differences. Omit URLs, passwords/tokens and full startup output. See [timing interpretation](PERFORMANCE.md#how-to-interpret-the-logs). Results are not required to finish the source changes.

## App comfort and retained settings

Create and Library images open the same original-resolution viewer. Pinch zoom is 1–5× with pan/reset. A small corner **i** button opens a separate scrollable metadata dialog; details no longer cover the image by default. Save, Use seed and Use settings remain available. Only the viewed image requests an original-size bitmap; device memory/smoothness remain unverified.

Draft edits save automatically to the primary private preferences and a second private backup containing only generation settings. If the primary draft cannot decode, the backup repairs it. Normal exit/relaunch retains prompts, canvas, style/weight, seed mode, preset and acceleration choice; explicit Forget clears both. This is not a guarantee against abrupt power/storage failure. New image records preserve style weight and intentional empty negative prompts; historical missing values retain fallbacks.

Rotation is now allowed. The draft/batch stay in the ViewModel, and selected image, zoom/pan and information visibility use saveable state with panning clamped to the resized viewport. Verify rotation while editing and inspecting an image; no device run was performed.

Verify: edit every setting, leave/reopen the app, and confirm restoration; open an image, pinch/pan/reset and inspect seed/settings only via **i**. Check new empty-negative/LoRA records and an older record. Verify Forget does not resurrect the backup. These are device checks, not performed here.

Old Draft/custom editable settings map to the nearer 18/24-step preset (ties/invalid values choose Balanced); the exact retired acceleration LoRA maps to Balanced/no LoRA and is hidden from choices. Stored historical metadata and already accepted batches are not rewritten. Use settings restores a supported current recipe. No Drive model/output file was deleted.

## Reversal and deferred candidates

Settings above provide small independent reversals. File snapshots preserve relative paths under `.work-speed/original/`, `speed-pass2-original/`, `warmup-pass-original/`, `t4-flash-original/`, `png-fast-original/`, `clip-skip-original/`, `two-presets-original/`, `speed-extras-original/` and `data-fidelity-original/`; use the corresponding pre-change snapshot and keep coordinated phone/notebook changes together.

TensorRT conversion/loaders, model replacement, forced full VRAM residency, T4 Triton compilation and K/V projection caching remain deferred. An inspected cuBLAS extension has stream/tail correctness concerns and is not enabled. Unsupported native kernels are not working accelerators just because a flag exists. Details and primary sources: [GPU research](GPU_ACCELERATION_RESEARCH.md).
