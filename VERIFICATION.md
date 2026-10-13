# Current app and recovery verification — 2026-10-09

Current 0.3.2 audit fixes, rebuilt APK and fresh local evidence are in [SECOND_AUDIT.md](SECOND_AUDIT.md). The previous audit is recorded in [EXTENSIVE_VERIFICATION.md](EXTENSIVE_VERIFICATION.md). The UI/pairing update is described in [APP_REFRESH.md](APP_REFRESH.md). The preceding backend repair is recorded in [RECOVERY_VERIFICATION.md](RECOVERY_VERIFICATION.md). Exact runtime startup: [RECOVERY_STARTUP.md](RECOVERY_STARTUP.md). The records below concern the earlier October 1 delivery; their notebook/APK hashes do not identify the current artifacts. No live device/GPU result is claimed.

## Historical delivery evidence

# Verification for Phone Studio 0.2.0 — router and editing

The matching deliverables are in `finished things/Phone Studio - 2026-10-01 - router and editing/`. Previous 0.1 bundles remain frozen. The APK is an installable **debug build**, application ID `app.phonestudio`, version **0.2.0/code 2**, Android 8.0/API 26 minimum and API 35 target. It has not been installed or opened on a device here.

| Completed local check | Result | Scope |
| --- | --- | --- |
| Android build | Passed | Kotlin/resources compile and debug APK packaging; final build completed offline. |
| Android unit tests | **43 passed**, zero failures/errors/skips | Existing connection, generation, HTTP and workflow tests plus 12 router-contract/edit-draft tests. |
| Android lint | **No issues found** | No reported errors, warnings or information items; narrowly documented compatibility/durability exceptions remain. |
| Router tests | **104 passed** | CPU fixtures, temporary files, image/mask composition, local mock HTTP services, journal recovery, LLM response validation and pinned-setup inspection. No real model inference. |
| Worker source checks | **27 passed** | Saved notebook JSON/Python syntax, original cell structure, embedded helpers, acceleration defaults, app forwarding and persistence. |
| Router-stage source/artifact checks | **27 passed** | Both notebooks unexecuted, unique cell IDs, syntax, exact 13 router-source embeds, exact worker edit helper, test/lint reports and APK freshness. |
| APK signature/identity | Passed | Debug signature verified with Android build-tools; package/version/minimum/target SDK inspected without installing. |
| Finished bundle integrity | SHA-256 manifest and archive checks | Copies must match verified APK/notebook hashes; every archived source file is compared with the saved source. |

These checks establish build and local contract correctness within their scope. They do **not** establish measured generation speed, visual quality, model VRAM fit, native CUDA compatibility, device behavior or end-to-end reliability.

## Evidence and reproducibility

The current machine-readable report is `.work-router/final_verification.json`; the worker report is `.work-speed/final_speed_source_review.json`. Detailed evidence is `.work-router/router-test-report.xml`, `.work-router/final_android_build.log`, `.work-router/apk_signature.txt`, `.work-router/apk_identity.txt`, and Android's XML unit/lint reports under `app/build/`. Copies of the final evidence accompany the finished bundle.

```text
./gradlew :app:testDebugUnitTest :app:lintDebug :app:assembleDebug
python -m pip install -r tests/router/requirements-dev.txt
python -m pytest tests/router -q
```

The local Android build used JDK 21.0.10, Gradle 8.10.2, SDK/build-tools 35, AGP 8.7.3, Kotlin 1.9.25 and Compose compiler 1.5.15, with JVM target 17. Router tests used Python 3.12. The notebooks were parsed and their embedded files compared; no cells, native installers, GPU probes, CUDA kernels, downloaded model weights or phone UI were run.

Local checks caught and corrected journal snapshot/WAL recovery, prepared-edit recovery, source/studio identity, stale callback updates, nested worker availability, download terminal-state handling and painted-mask viewport mapping. CPU image fixtures verify exact preservation of zero-mask normalized pixels; they cannot establish whether actual generated edits look good.

## Warning cleanup and deliberate exceptions

The previous warning cleanup remains: the portrait lock was removed, retry counters use primitive integer state, and the HTTP callback parameter matches its interface. Viewer selection/zoom/pan/information state survives saved-state recreation in code; gestures, rotation and lifecycle behavior still need a phone check.

Six dependency-version suggestions remain narrowly acknowledged per coordinate because their suggested upgrades require a different SDK/compiler/build setup. The existing matched stack remains pinned: Compose BOM, Core, Lifecycle runtime/Compose, Activity and serialization. There is no global lint disable or baseline. See the [official Compose/compiler pairing table](https://developer.android.com/jetpack/androidx/releases/compose-kotlin) and the [serialization compiler requirement](https://github.com/Kotlin/kotlinx.serialization/blob/master/CHANGELOG.md#170--2024-06-05). This stage adds free AndroidX ExifInterface 1.4.2 for orientation handling without a toolchain migration.

Method-scoped `ApplySharedPref` exceptions retain deliberate durable request/draft/terminal-state writes. Changing those writes to asynchronous `apply` would weaken recovery ordering; see [Android's editor contract](https://developer.android.com/reference/android/content/SharedPreferences.Editor). Cosmetic router progress does not trigger a durable write on every poll. Some small initial submission/reset writes still occur on the main thread; a safe asynchronous ordering redesign is outside this stage.

## Remaining runtime checks and limits

Follow the seven checks in [ROUTER_GUIDE.md](ROUTER_GUIDE.md#runtime-verification-and-evidence): assistant/worker readiness, visual selection, saved switches, masked-edit preservation, draft persistence, interruption recovery and warm timing. The [performance inspection](PERFORMANCE.md), [speed defaults/rollback](SPEED_MODES.md) and [GPU research](GPU_ACCELERATION_RESEARCH.md) retain the earlier pipeline, ranked estimates and per-change checks.

The approximately 12 GiB pinned LLM/projector bundle is a tight **unverified** candidate for a separate 16 GB-class GPU. Initial download/build cost is separate from warm generation. Same-weight CPU-projector fallback is disclosed; no silent smaller-model substitution exists. Publisher-described uncensored/abliterated weights do not guarantee zero refusals or prove the best possible model.

Prompt enhancement, Fast and experimental acceleration can change images. The per-render phone switch does not reset launch-time precision/compile choices. Editing bypasses incompatible per-render hooks. Supported WAI v170 replacement/outpaint recipes can use the default-enabled auxiliary inpaint patch; other recipes use a labeled ordinary edit graph. Advanced IPAdapter/ControlNet and uncommon `model_as_lora` combinations are not implemented or validated with the auxiliary patch and remain outside the supported recipe.

Only one active router may use a persistent state folder. Four independent credential/tunnel configurations do not establish free-tier eligibility or bypass capacity limits. No paid services were provisioned. An LLM-guided SDXL workflow cannot promise ChatGPT/Gemini/Grok editing quality; identity, typography, segmentation and multi-object edits need actual-image evaluation.

For later diagnosis, send GPU/runtime versions, requested/active flags, placement/degraded status, three distinct warm seeds and matching worker, `PhoneStudioTiming` and `[phone-studio-router-timing]` lines. Include visual examples if evaluating selection/editing; omit credentials. No runtime results are required to use or inspect this finished version.
