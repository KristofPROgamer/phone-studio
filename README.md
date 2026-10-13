# Phone Studio

Phone Studio 0.2 connects a native Android app to one private router and three image workers. The router hosts a self-contained vision-language assistant, improves prompts, coordinates rendering, stores every version, and selects the closest match. Editing starts from a previous image or a photo-picker upload.

There are **two notebook types**:

- `PHONE_STUDIO_COLAB.ipynb`: generation/edit worker, run independently on each of the three worker runtimes.
- `PHONE_STUDIO_ROUTER_COLAB.ipynb`: fourth runtime, router plus the local Huihui-Qwen3.8-27B-abliterated vision model.

The phone saves **only the router connection** for new jobs. Previously saved worker connections remain available for old images and accepted legacy batches.

## Start here

1. Start the three worker notebooks. Each needs its own valid GPU runtime, ngrok configuration, tunnel password and studio token. Keep the same desired checkpoint and LoRA files available on each worker.
2. Start the router notebook on its own GPU runtime. Store the three worker connection records in its `PHONE_STUDIO_WORKERS_JSON` Secret. Router credentials and tunnel configuration are independent of worker credentials.
3. In the phone's **Connect** tab, add the router URL and its username, password and studio token. Check that the assistant and the intended workers are ready.
4. In **Create**, choose a checkpoint and describe the image. Prompt assistance and visual selection default on; their switches are saved. **Other versions** reveals retained alternatives.
5. For editing, use the pencil button on an image, or select **Edit image → Choose an image**. Describe the change. Automatic area selection is the default; **Paint area** lets you correct the selection.

See [setup and usage](ROUTER_GUIDE.md), [model identities and limits](ROUTER_MODEL.md), [planned architecture](ROUTER_STAGE_PLAN.md), [interface contract](ROUTER_API.md), and [verification](VERIFICATION.md).

## What stays saved

Generation prompts, negatives, model/LoRA choices, two sampling presets, seed policy, speed and assistant switches save automatically. The editing draft is separate: source image, instructions, preservation choice and painted mask remain in app-private storage. Closing the app, rotating, or switching modes does not intentionally reset them. Source uploads are copied into private storage immediately, so expired picker grants cannot erase the draft.

The phone stores up to 60 image records, including alternative versions. With three candidates per request this is approximately 20 requests. Images themselves live in router storage and its configured persistent folder. The viewer has a small information button, pinch zoom, reset zoom, gallery export and an edit button. Metadata includes original prompt, effective tags, review status/reason and source/edit lineage.

Accepted jobs have saved request IDs, studio identity and job IDs. A foreground service follows a router job while the app is backgrounded. Reconnecting reads the saved request rather than blindly creating another GPU render. A changed router state folder is reported explicitly. **Stop** attempts targeted cancellation; older workers may finish an already accepted render. Retrying uses a durable retry key and only confirmed failed workers; uncertain worker acceptance is never blindly resubmitted.

## Generation and editing choices

Only **Balanced (24 steps)** and **Fast (18 steps)** are exposed, using CFG 6.5 and `dpmpp_2m`/`karras`. Canvas choices remain 768×1024, 1024×1024 and 1024×768. Fast, prompt enhancement and experimental acceleration can change output. The selected settings and effective prompt are recorded.

The existing speed improvements remain in the worker notebook: GPU-resident execution where possible, local model/cache paths, guarded attention/conditioning optimizations, warm-up and binary image responses. Optional experimental worker features are requested on by default as previously authorized; unsupported features remain gated with visible status. The phone's extra-acceleration switch controls per-render hooks. Launch-time precision/compilation choices still require a worker restart. Editing bypasses incompatible per-render acceleration hooks to protect the edit graph. Details and rollback are in [speed settings](SPEED_MODES.md), [performance inspection](PERFORMANCE.md), and [GPU research](GPU_ACCELERATION_RESEARCH.md).

Editing keeps the chosen SDXL checkpoint. The assistant plans whole-image changes, local refinements/replacements, or outpainting. Automatic local selection uses pinned SAM2.1 Tiny on CPU when compatible; uncertain selection returns a request for a painted mask. Supported WAI v170 replacement/outpaint workers can use the pinned Fooocus auxiliary inpaint patch/head. An ordinary same-checkpoint fallback is labeled. Local edits are cropped with context and composited back onto the normalized source; zero-mask pixels are preserved. Whole-image edits can change the whole image. Source assets are never overwritten.

The saved **Stronger inpainting** app switch defaults on; disabling it requests the ordinary edit graph. The actual method is recorded per candidate. Prepared edit crops/masks are persisted before worker submission and reused when recovering an accepted edit.

## Model and infrastructure

The selected assistant is the report's uncensored/abliterated Huihui 27B vision model, served locally with pinned llama.cpp and verified GGUF/projector hashes. No external paid AI provider or added content-moderation service is used. “Uncensored” is the publisher's model description, not a guarantee of zero refusals. The chosen approximately 12 GiB weight/projector bundle is a practical candidate for a separate 16 GB-class GPU; actual fitting, placement, speed and visual judgment remain unverified. Same-weight CPU-projector fallback is reported clearly.

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

Finished app/notebook/source bundles are versioned under **finished things**. Previous 0.1 snapshots are frozen. Rollback source for this stage is under `.work-router/original/`; active source and the latest finished bundle are identified in [VERIFICATION.md](VERIFICATION.md).

## Security and storage

HTTPS, tunnel Basic authentication and a separate studio token protect router APIs, assets and sockets. Phone authentication is scoped to the saved origin/path; no worker credentials enter responses or LLM prompts. The LLM binds only to loopback with its own private API key. Redirects and automatic mutating-request retries are disabled. LLM output is validated data and cannot choose shell commands, URLs, model files or arbitrary graphs.

Sources/masks are bounded to 24 MiB and 16 megapixels, normalized, and assigned opaque IDs. Router SQLite WAL lives on runtime-local disk; critical standalone snapshots and asset copies go to persistent storage. Run exactly one active router per state folder. A local process lock does not establish distributed locking across independent VMs. The default asset budget is 2 GiB; active dependencies are protected, and older unused assets can expire. LLM weights stay on local disk by default to avoid exhausting free Drive storage alongside image models.

Credentials use Android encrypted storage where the device supports it. Drafts and library metadata contain no connection secrets. **Forget everything** is an explicit local reset; persistent server images and saved gallery copies are not deleted.
