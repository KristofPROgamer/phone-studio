# Phone Studio 0.2.0 — finished router/editing stage

This is the matched finished snapshot dated 2026-10-01. Previous finished versions remain separate.

- `Phone Studio 0.2.0.apk`: installable **debug** Android app, version 0.2.0/code 2, Android 8.0+.
- `PHONE_STUDIO_COLAB.ipynb`: self-contained image worker; run three independent instances.
- `PHONE_STUDIO_ROUTER_COLAB.ipynb`: fourth runtime, router plus pinned local Huihui-Qwen3.8-27B-abliterated vision model.
- `Phone Studio 0.2.0 source.zip`: matching Android/router/setup/notebook/test/documentation source and Gradle wrapper.
- `verification/`: final local reports and saved-source hashes.
- `SHA256SUMS.txt`: hashes of this bundle's files.

The phone uses one router connection. Prompt-to-tag assistance and visual selection default on; the best reviewed candidate is shown by default and alternatives remain accessible. Edit a past image or a private photo-picker copy with automatic or painted area selection. The saved **Stronger inpainting** switch defaults on; supported WAI v170 recipes use the auxiliary patch, with an explicit ordinary-graph fallback. Generation/edit drafts, masks, settings and accepted job IDs persist. Existing two presets, speed switches, corner information control and pinch/reset viewer remain.

Start the three workers with independent credentials, then start the router with their private connection records, and connect the phone to the router only. See [ROUTER_GUIDE.md](ROUTER_GUIDE.md) for Secrets, setup, recovery and seven runtime checks. Install the APK manually; no device installation was performed here.

**Completed checks:** 43 Android unit tests, 104 CPU/mock router tests, clean Android lint, 27 worker source checks, 27 stage/artifact checks, successful APK build and debug-signature verification. Packaging also checks each archive entry and copied artifact against current saved files.

**Unverified:** Colab execution, real LLM/GPU fit/performance, phone gestures/lifecycle, automatic segmentation and generated-image quality. No measured speedup or proprietary chatbot editing parity is claimed. The approximately 12 GiB model/projector bundle is a tight, unverified 16 GB-class GPU candidate; same-weight CPU-projector fallback is disclosed. The model is publisher-described uncensored/abliterated, not a promise of zero refusals or proven absolute best quality. No paid service was provisioned; independently configured accounts do not establish runtime eligibility or bypass quotas.

Experimental speed settings can change pixels, and launch-time settings require a worker restart. See [VERIFICATION.md](VERIFICATION.md), [ROUTER_MODEL.md](ROUTER_MODEL.md), [PERFORMANCE.md](PERFORMANCE.md) and [SPEED_MODES.md](SPEED_MODES.md) for evidence, limits and rollback. Advanced adapter combinations remain outside the supported auxiliary edit recipe.

The source archive excludes local SDKs, caches, virtual environments, private credentials, runtime state, model weights and working backups. Full local rollback copies remain in the project workspace. This stage is complete at the stated verification scope; further feature work awaits your instructions.
