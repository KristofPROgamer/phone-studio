# Current recovery baseline — 2026-10-08

Follow [RECOVERY_STARTUP.md](RECOVERY_STARTUP.md) with the two current cleared notebooks. Default assistant: pinned 4B Q4_K_M plus matching f16 projector. Normal router setup uses official b11146; source compilation and automatic CPU-projector retry are off. Worker `COMPATIBILITY_MODE=True` skips optional native attention/install/compile and image-changing experiments. Automatic SAM is off; manual-mask editing still requires the functioning LLM planner.

The confirmed schema wrapper is fixed. Inference categories and last-result health distinguish a reachable process from usable tasks. Independent health results survive a slow third-worker check; explicit catalog refresh bypasses worker caches. Prebuilt publication probes staging before promotion, checks dependent-file integrity, and retains private diagnostics. Selected-profile/process fingerprints control reuse.

Use the actual adapter smoke and four-image test before phone generation/editing. Host RAM/VRAM, exact model fit/quality and isolated third-worker recovery remain live checks; no Colab session/phone was available locally. The local Windows RTX 2060 SUPER is outside the selected Linux T4 deployment and was not used for model inference.

The following findings are historical. Their 27B assumptions, source-build timeout advice and instructions for patching older open notebooks are not the current recommended startup. Preserve them only as prior evidence; upload the final cleared notebook instead.

## Historical notes — 2026-10-03

# Runtime setup findings — 2026-10-03

The router's serving cell prints a bounded startup health summary after letting its initial 10-second health cache expire: LLM readiness, each worker's online/checkpoint count and whitelisted editing/acceleration capabilities; a failed diagnostic reports only its exception type and leaves the server running.

## An occupied router port

The live router API encountered `OSError: [Errno 98] Address already in use` on its original localhost port 8080. The serving cell now probes ports 8080, 8082, 8083 and 8084 and selects the first available one. It exports that value through `PHONE_STUDIO_ROUTER_PORT`, and its authenticated health requests and ngrok tunnel use the same selected port. Port 8081 remains reserved for the already-loaded private LLM; unrelated port owners are never terminated. If all four choices are occupied, setup stops with a clear message. A probe does not reserve the port after it closes; a competing process can still cause a later bind failure, which requires inspecting the concrete log.

**Verify:** check `Router local port` and confirm the authenticated router health response and printed public URL work after launch. Restarting the serving cell after this correction reuses the loaded LLM; it does not require downloading or loading the model again.

## Separate Drive and runtime-local disk reserves

The first live worker setup reported `Fooocus unavailable: Not enough free space for the Fooocus auxiliary weights and the configured disk reserve.` Generation and stock SDXL edits remain available after this optional setup failure.

The original auxiliary call reused the 8 GiB **runtime-local** model-cache reserve while downloading Fooocus weights to **Google Drive**. Its space check therefore required about 9.23 GiB free in Drive for the 1.23 GiB patch. Colab's local-disk meter measures a different filesystem and cannot establish available Drive quota.

The current worker notebook uses `FOOOCUS_DRIVE_RESERVE_GB = 0.5` only for the optional Fooocus downloads. The space check still requires enough room for the complete artifact plus 512 MiB of remaining Drive space. Model-cache, output-cache and T4 build reserves remain at `MODEL_CACHE_RESERVE_GB = 8`. File size/hash validation, the pinned weights and source, and the notebook-to-app interface are unchanged. This lowers a storage reserve; it does not make inference faster or establish image quality.

**Verify:** inspect the worker's actual Drive free space, rerun its auxiliary setup, and confirm `Pinned Fooocus auxiliary prepared` followed by `fooocusInpaint: true` in the authenticated worker health response after server startup. If Drive lacks room, leave the honest stock fallback in place or make room deliberately; do not delete models automatically.

### Correcting an already-open older notebook

Finish the current warm-up before making this optional correction. Interrupt the final server cell intentionally once its warm-up has finished. In the GPU settings cell (zero-based index 3), add:

```python
FOOOCUS_DRIVE_RESERVE_GB = 0.5
```

In the next auxiliary setup cell (zero-based index 4), change its final call from `reserve_gb=MODEL_CACHE_RESERVE_GB` to `reserve_gb=FOOOCUS_DRIVE_RESERVE_GB`. For an already-initialized runtime, assigning the new variable immediately before that final call also avoids rerunning unrelated GPU setup. Run the auxiliary setup cell, then run the final launch cell again. The new process imports the registered auxiliary nodes and receives the updated readiness flag. Reuse the actual printed worker connection values in the router configuration.

A full notebook reinstall, a paid dependency, a different checkpoint, and an ephemeral `/content` symlink stored in Drive are unnecessary for this correction. Previously finished bundles remain frozen; use the corrected working notebook when starting new runtimes.

## First warm-up includes startup costs

The existing two-step, 768 × 1024 warm-up includes the first copy from Drive, model loading, GPU allocation/autotuning, sampling and VAE decoding. The existing deadline is 900 seconds. A `Warm-up still running` line at 208 seconds alone does not establish a stalled sampler. The local-cache hook prints `Caching ... on local disk...` before the blocking copy and `Local copy ready in ...s` afterward. Inspect those stage messages and any actual exception before changing settings.

**Verify:** wait for `Warm-up complete`, the printed connection block, and a successful authenticated worker health response; collect elapsed times separately from subsequent renders. Warm-up completion checks that decoded output exists, not its visual quality. A timeout, process exit or worker history error still requires inspecting the concrete log. No warm-render speed improvement or visual quality has been measured for this storage correction.

## Prefer the verified official server binary

`USE_PREBUILT_SERVER = True` now downloads the official [llama.cpp b11146 release](https://github.com/ggml-org/llama.cpp/releases/tag/b11146) from the same pinned commit `7fe450e19305b828c199d602c23a8337aaa1f03b`. Both the CUDA 12.8 Linux x86_64 server archive and its matching runtime archive have fixed byte counts and SHA-256 checks. Extraction accepts only confined regular files, directories and internal library symlinks; the runtime libraries stay beside the server under `/content/phone_studio_llm_prebuilt`. Existing compiler caches, Colab Torch/CUDA packages and system libraries are not replaced.

The prebuilt needs glibc 2.38+ and compatible C++/GPU-driver libraries. Before loading model weights, `--version` must identify the pinned commit and `--list-devices` must report a CUDA GPU. `ALLOW_SOURCE_BUILD = False` prevents silently beginning another lengthy compilation if these checks fail. Source building requires explicit opt-in; the 90-minute parameter below applies only to that option. The model, GGUF quantization, projector and inference settings stay the same.

**Verify:** confirm both archives verify, the version identifies `7fe450e`, the device probe reports the intended GPU, and `Native image understanding is ready` appears. The saved setup response identifies `serverSource`. These startup checks establish binary compatibility and model health, not image-review accuracy or a guaranteed startup duration. Do not overlap a pre-existing compiler job with a second source build.

## Allow enough time when explicitly building from source

The live router reached the previous 1,800-second build limit while its compiler log was around 37%. Compiler descendants were still active after the notebook received the timeout. This is a startup timeout, not an LLM inference error or evidence that its selected weights cannot fit.

For an explicitly enabled source build, the working router notebook sets `ROUTER_BUILD_TIMEOUT_SECONDS = 5400` (90 minutes), forwarded through `setup_runtime` to `build_server`. Only integer values from 600 to 7200 seconds are accepted. The pinned llama.cpp revision, CUDA architecture, model/projector files and two compiler jobs (`-j 2`) are unchanged. The startup output identifies the limit and private progress log; timeout messages explain retaining the cache and avoiding overlapping compiler processes. Existing timeout/process cleanup behavior is unchanged by this correction.

**Verify:** watch `/content/phone_studio_llm_build/setup.log` for continued progress, then confirm the pinned server binary and `server-build.json` are produced before LLM startup. After a timeout, confirm compiler descendants have finished or stopped before retrying against the same build directory; do not start a second build alongside the first. Already-loaded authenticated LLM sessions and valid stamped builds still reuse their existing process/binary. This change extends initial build allowance; it does not claim faster rendering.
