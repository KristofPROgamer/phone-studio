# Phone Studio 0.3.2 — second audit, 9 October 2026

This is a focused follow-up to the frozen 0.3.1 delivery. Install the **0.3.2/code 5 debug APK over the existing app**, retaining its data and signing identity. The exact startup sequence remains in [RECOVERY_STARTUP.md](RECOVERY_STARTUP.md).

## Confirmed defects and repairs

| Defect | Repair |
| --- | --- |
| A router interruption during Cancel could leave the parent recorded as cancelled while accepted workers were still queued/rendering. | Cancellation intent is durable and nonterminal until outcomes are known. One owned task coalesces repeat Cancel; startup resumes cancellation without submitting new render graphs. Unconfirmed outcomes retain uncertainty and recovery identity. |
| A committed local job followed by failed persistent backup was returned as accepted by recovery but never scheduled. | Status/request recovery retries pending durability before scheduling the same saved nonterminal job. The request/job IDs stay unchanged. Ordinary status polling does not repeatedly back up an unchanged journal. |
| Explicit retry after confirmed queue cancellation followed a deleted prompt indefinitely. | Confirmed cancellation is distinguished from unresolved acceptance. Only an explicit targeted retry rotates that cancelled worker's identity; successful/uncertain peers stay protected. |
| Old notification Stop actions could cancel newer batches, or start foreground mode and leave an idle service running. | Both the action's authority and PendingIntent identity are bound to its batch. Missing/stale actions follow normal resume/idle cleanup. Completed legacy peers stay completed when another target is stopped; unresolved targets retain recoverable IDs and images. |
| Legacy warm-up could enqueue more work while an accepted render still needed recovery. | Warm-up uses the same unresolved-work guard as Generate. |
| Storage failures during connection removal/disconnect could escape into the UI; client identity writes ignored failure and explicit credential forgetting was asynchronous. | Safe notices retain the last saved connection state. A recovery client ID is returned only after checked persistence, including retries after failed in-memory writes. Credential forgetting is checked before removing published saved IDs. |
| Failed gallery writes left pending rows/files, final publication could fail while still reporting success, and concurrent legacy saves could select the same filename. | Failed exports clean up only their own new entry, success requires publication, and file reservation is atomic. Existing photos remain untouched. |
| Extreme numeric or deeply nested JSON replies escaped safe LLM validation and left misleading inference health. | Numeric overflow and recursive JSON failures enter the existing categorized diagnostics and fallback behavior, without exposing reply bodies. |
| The assistant's 180-second cap excluded image preparation, and expired jobs could still decode images before noticing their deadline. | One task-entry budget covers preparation waits, queue and HTTP; expiry is checked before each image. An already-running decode thread cannot be hard-stopped, and its existing byte/pixel bounds remain in force. |

The pinned 4B model/projector, single gated 9B fallback, server/schema contract, protocol 2, checkpoint, generation presets, masks, saved credentials and existing app/UI remain the baseline. No dependency upgrades, weight downloads, GPU compilation, live service resets or additional feature work were performed.

## Verification and scope

Fresh results are recorded in `.work-router/audit2-verification-2026-10-09/verification.json`, with source hashes, commands, timestamps, test/lint counts, signature/identity, backup/frozen-bundle checks and changed/added-file inventory. Earlier reports remain historical. Python uses temporary journals, CPU images and synthetic worker/LLM replies; Android uses JVM fixtures for actual storage/API/runner code and plain cancellation/export rules. These checks do not establish live model/rendering/phone success.

| Completed local check | Result |
| --- | --- |
| Android JVM tests | **111 passed**, zero failures/errors/skips. |
| Python/router suite | **313 passed**, **15 subtests passed**, one Linux-only process-group fixture skipped on Windows; 48.98 seconds. |
| Android compile, lint and APK | Passed offline; lint reports **zero issues**. APK version **0.3.2/code 5**, same application ID and signing certificate as 0.3.1. |
| Notebook synchronization | Cleared outputs, preserved cell IDs, exact **17** router sources and **5** worker helpers, syntax, baseline flags and confined producer determinism/idempotence pass. |
| Worker baseline policy | **28 static checks passed**; normal optional compilation stays disabled. |

The first full Python run found a test that incorrectly assumed a fixed launch order for parallel workers. Its assertion now checks exact per-worker call counts, including successful peers running once and the cancelled worker alone retrying. The focused case and final full suite passed. The earlier failed attempt remains separately labeled in the evidence folder; it is not the final acceptance result. No further Android rebuild was needed after this test-only correction.

Run current artifact checks in the original workspace:

```powershell
& '.\.work-router\test-venv\Scripts\python.exe' '.\.work-router\verify_audit2.py'
```

When code changes, run the appropriate bounded fresh checks:

```powershell
& '.\.work-router\test-venv\Scripts\python.exe' '.\.work-router\run_audit2_checks.py' router
& '.\.work-router\test-venv\Scripts\python.exe' '.\.work-router\run_audit2_checks.py' android
```

The preference fixtures distinguish memory updates from successful disk writes, matching [Android's preference implementation](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/main/core/java/android/app/SharedPreferencesImpl.java). They do not validate a real device's KeyStore or storage hardware. Gallery fixtures cover owned-entry cleanup/publication and concurrent temporary-file reservation; MediaStore behavior still needs a phone.

Both cleared notebooks and their exact embedded sources are checked and regenerated together. The APK uses the existing toolchain and signing certificate. Every packaged file and archived manifest entry is SHA-256 checked; ZIP CRC is checked. Frozen 0.3.1 remains intact. The separate source-copy build documented in the previous audit is historical; this audit compiles the changed current sources in the workspace and verifies delivered copies against them.

No connected phone/emulator or permitted live GPU notebook is available. Camera/permissions/UI/lifecycle, actual installation/data retention, real 4B inference/quality/memory headroom, SDXL generation/manual editing and three-worker/rejoin acceptance remain pending. The historical RAM hypothesis and intermittent worker cause remain unproven. Follow the bounded live checks in [RECOVERY_STARTUP.md](RECOVERY_STARTUP.md), preserving successful and uncertain accepted work.

## Rollback

Before these repairs, all **144** public source/artifact files were hash-checked and backed up to `.work-router/audit2-backup-20261009T122949Z/`. Its manifest includes the preceding 0.3.1 APK. The frozen bundle's **182** files and ZIP were also verified before changes. Private credentials, app data, journals, assets and model caches were neither copied nor reset.

When work is idle, verify backup hashes and restore changed source/notebook/producer/docs at matching relative paths; move update-only files aside using the current report's inventory. Restore app and embedded notebook sources together. Preserve runtime/app data and frozen deliveries. Complete or confirm cancellation of unresolved work before downgrading; the older backend does not understand the new in-progress cancellation phase.

Android normally rejects code 4 over code 5. Keep the same signing key and rebuild backed-up sources with a version code above 5, or deliberately use a supported debug data-preserving downgrade (`adb install -r -d`) with the backed-up APK. Neither device procedure was run here. Do not uninstall or clear app data to bypass the version check. Restoring files alone does not downgrade an installed app.
