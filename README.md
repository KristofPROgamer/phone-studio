# Phone Studio

Phone Studio 0.3 connects a native Android app to one private router and up to three image workers. The router hosts a self-contained vision-language assistant, improves prompts, coordinates rendering, stores every version, and selects the closest match. Editing starts from a previous image or a photo-picker upload.

The app now has QR/paste connection setup, a focused creation screen, collapsible settings, smoother transitions, and library/model search. [APP_REFRESH.md](APP_REFRESH.md) describes installation, the simpler setup, verified checks and rollback. Existing authentication and saved work remain in place.

There are **two notebook types**:

- `PHONE_STUDIO_COLAB.ipynb`: generation/edit worker, run independently on each of the three worker runtimes.
- `PHONE_STUDIO_ROUTER_COLAB.ipynb`: separate runtime, router plus the pinned Huihui-Qwen3.5-4B-abliterated Q4_K_M vision model and matching f16 projector.

The phone saves **only the router connection** for new jobs. Previously saved worker connections remain available for old images and accepted legacy batches.

## Start here

1. Follow [exact repaired startup and acceptance](RECOVERY_STARTUP.md). Upload the two current cleared notebooks; keep existing Secrets, checkpoint and saved data.
2. Start one worker first with `COMPATIBILITY_MODE=True`; wait for decoded warm-up and authenticated health. Leave healthy workers/accepted jobs alone.
3. Start the router on its separate permitted Linux T4 runtime. Ordinary setup uses pinned binaries without CUDA compilation. The next cell runs two actual LLM adapter calls; inspect their structure and semantic expectations.
4. On the updated phone app, scan the router's private QR or paste its setup code and review the address before connecting. Manual fields remain available. Complete one Balanced generation and one manual-mask edit before adding the other two workers.
5. Validate one three-worker generation and an isolated third-worker restart/rejoin. Confirm recovery retains successful/uncertain accepted work without duplicate renders.

See [setup and usage](ROUTER_GUIDE.md), [model identities and limits](ROUTER_MODEL.md), [planned architecture](ROUTER_STAGE_PLAN.md), [interface contract](ROUTER_API.md), and [verification](VERIFICATION.md).

Live startup findings and small setup corrections are documented in [runtime setup notes](RUNTIME_SETUP.md).

## What stays saved

Generation prompts, negatives, model/LoRA choices, two sampling presets, seed policy, speed and assistant switches save automatically. The editing draft is separate: source image, instructions, preservation choice and painted mask remain in app-private storage. Closing the app, rotating, or switching modes does not intentionally reset them. Source uploads are copied into private storage immediately, so expired picker grants cannot erase the draft.

The phone stores up to 60 image records, including alternative versions. With three candidates per request this is approximately 20 requests. Images themselves live in router storage and its configured persistent folder. The viewer has a small information button, pinch zoom, reset zoom, gallery export and an edit button. Metadata includes original prompt, effective tags, review status/reason and source/edit lineage.

Accepted jobs have saved request IDs, studio identity and job IDs. A foreground service follows a router job while the app is backgrounded. Reconnecting reads the saved request rather than blindly creating another GPU render. A changed router state folder is reported explicitly. **Stop** attempts targeted cancellation; older workers may finish an already accepted render. Retrying uses a durable retry key. Confirmed execution failures target only the failed worker; known accepted follow/image-copy failures retain their IDs and recover that result without another render. Uncertain worker acceptance is never blindly resubmitted.

## Generation and editing choices

Only **Balanced (24 steps)** and **Fast (18 steps)** are exposed, using CFG 6.5 and `dpmpp_2m`/`karras`. Canvas choices remain 768×1024, 1024×1024 and 1024×768. Fast, prompt enhancement and experimental acceleration can change output. The selected settings and effective prompt are recorded.

Compatibility mode is the current working baseline. It preserves local model/output caches and ordinary transport, while disabling optional T4/Sage native attention, automatic compilation, approximate denoising/conditioning and experimental FP16 settings. The phone's saved acceleration switch cannot override it. Existing opt-in implementations remain available; their older speed documentation applies only after explicitly disabling compatibility mode.

Editing keeps the chosen SDXL checkpoint. The assistant plans whole-image changes, local refinements/replacements, or outpainting. Automatic local selection is off for the baseline; explicit opt-in uses guarded pinned SAM2.1 Tiny on CPU when compatible; uncertain selection returns a request for a painted mask. Supported WAI v170 replacement/outpaint workers can use the pinned Fooocus auxiliary inpaint patch/head. An ordinary same-checkpoint fallback is labeled. Local edits are cropped with context and composited back onto the normalized source; zero-mask pixels are preserved. Whole-image edits can change the whole image. Source assets are never overwritten.

The saved **Stronger inpainting** app switch defaults on; disabling it requests the ordinary edit graph. The actual method is recorded per candidate. Prepared edit crops/masks are persisted before worker submission and reused when recovering an accepted edit.

## Model and infrastructure

The default assistant is the precisely pinned 4B vision model/projector pair (3.148 GiB of artifacts), served locally with official llama.cpp b11146. The adapter now sends the pinned server's nested JSON schema and reports categorized inference failures separately from process readiness. Host RAM and GPU VRAM are sampled independently; measured fit, quality and latency remain pending. Automatic CPU-projector retry and automatic segmentation are off. One pinned 9B pair is an explicit quality-only fallback after demonstrated essential 4B failure; it is not downloaded automatically.

Four independent credentials/tunnels are supported as configuration. The notebooks do not create accounts, start the other runtimes, purchase resources, or bypass quotas. Free managed Colab does not guarantee or support this deployment pattern; use permitted/local runtimes. [Colab FAQ](https://research.google.com/colaboratory/faq.html).

An LLM guiding SDXL cannot guarantee the editing quality of ChatGPT/Gemini/Grok image models. Exact identity, typography, complex multi-object edits and visual ranking need evaluation with actual images. Local checks do not establish image quality or speed.

## Build and development

Android 8.0/API 26 minimum; SDK 35 target. Build with JDK 17+, Gradle 8.10.2, Android Gradle Plugin 8.7.3 and Kotlin 1.9.25. The app uses Kotlin/Jetpack Compose, OkHttp and Coil. AndroidX ExifInterface 1.4.2 handles source orientation before lossless PNG normalization. It is a free dependency; no toolchain migration was needed.

```text
./gradlew :app:testDebugUnitTest :app:lintDebug :app:assembleDebug
python -m pip install -r tests/router/requirements-dev.txt
python -m pytest tests/router -q
```

CPU/router tests use fixtures and local mock HTTP services. Notebook code is parsed and its embedded sources compared without executing cells. Do not treat successful builds as device/GPU verification.

Source roles: `app/` is the Android client, `router/` contains the versioned API/journal/LLM/editing/worker orchestration, `tools/` contains bounded pinned setup helpers. Both notebooks embed their needed source so they do not require the repository mounted.

Finished app/notebook/source bundles are versioned under **finished things**. Previous 0.1 snapshots are frozen. Rollback source for this stage is under `.work-router/original/`; current repair backup and scoped evidence are identified in [RECOVERY_STARTUP.md](RECOVERY_STARTUP.md) and [RECOVERY_VERIFICATION.md](RECOVERY_VERIFICATION.md). Frozen finished bundles remain historical.

## Security and storage

HTTPS, tunnel Basic authentication and a separate studio token protect router APIs, assets and sockets. Phone authentication is scoped to the saved origin/path; no worker credentials enter responses or LLM prompts. The LLM binds only to loopback with its own private API key. Redirects and automatic mutating-request retries are disabled. LLM output is validated data and cannot choose shell commands, URLs, model files or arbitrary graphs.

Sources/masks are bounded to 24 MiB and 16 megapixels, normalized, and assigned opaque IDs. Router SQLite WAL lives on runtime-local disk; critical standalone snapshots and asset copies go to persistent storage. Run exactly one active router per state folder. A local process lock does not establish distributed locking across independent VMs. The default asset budget is 2 GiB; active dependencies are protected, and older unused assets can expire. LLM weights stay on local disk by default to avoid exhausting free Drive storage alongside image models.

Credentials use Android encrypted storage where the device supports it. Drafts and library metadata contain no connection secrets. **Forget everything** is an explicit local reset; persistent server images and saved gallery copies are not deleted.
