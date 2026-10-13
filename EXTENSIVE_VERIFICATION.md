# Phone Studio 0.3.1 follow-up audit — 9 October 2026

This record describes the frozen 0.3.1 checkpoint. Current repairs and evidence are in [SECOND_AUDIT.md](SECOND_AUDIT.md).

This update completes the interrupted local audit. Install **PhoneStudio-0.3.1-debug.apk** over the existing app, keeping its data. Application ID remains `app.phonestudio`; version code is **4**, with the same signing certificate. The preceding 0.3.0 delivery remains frozen.

## Confirmed issues repaired

- Notebook Basic-auth checks used a different encoding from the phone/server, and worker Secrets stripped significant password/token spaces. Supported Latin-1 password bytes now agree across the stack. Password spaces are preserved; unsupported characters and unsafe tokens fail before publication or expensive setup. Invalid existing credential files are retained. The legacy token-only worker path remains supported. Equivalent IPv6 worker endpoints cannot evade duplicate detection.
- App requests could resolve credentials from changed saved settings after capturing their endpoint. API/socket/edit-copy/gallery requests now capture both together and enforce their connection's origin/path. Gallery downloads have a 24 MiB streaming limit, including unknown-length responses.
- Render-state commits ignored disk failure and published state prematurely. Durable writes now succeed before state publication or network submission. Failure pauses work with recovery identity retained; it does not depend on a second successful disk write. Unresolved accepted work blocks a new Generate, removal, disconnect and forgetting, while allowing a same-ID connection repair.
- Recovery could retry an already running/finished parent job instead of collecting it. It now reads and validates status first. Eligible targeted retries keep an independent action key across ambiguous responses; a different parent/session/request is rejected. Legacy unresolved worker recovery retains accepted IDs.
- Stop could reconcile before a submission finished, or an old cancellation could clear a newer foreground render. Cancellation waits for the previous runner and checks ownership before cleanup. Unconfirmed remote cancellation retains recovery identity and is reported honestly; finished candidates remain available.
- An outer router deadline discarded the recoverable identity of known accepted workers. Fully identified accepted work now retains its identifiers, frozen render metadata and resume-only state. Unknown acceptance remains uncertain. Successful peers and saved candidates remain intact.
- Pending notification/gallery actions were lost on Activity recreation. Minimal action identity is now saved and consumed once. Scanner Close remains above the bounded preview; instructions scroll; AUTO-focus cameras get bounded refocusing with owned cleanup. Switch labels support accessibility, and image information distinguishes requested acceleration from execution.

The pinned 4B vision model/projector, llama.cpp server/schema repair, protocol 2, SDXL checkpoint, generation defaults and mask/render contracts remain the repaired baseline. No toolchain upgrade, model search, GPU compilation, weight download or live service reset was performed.

## Current verification

Current source-bound results, timestamps, commands, counts, signatures and file inventory are recorded in `.work-router/extensive-verification-2026-10-09/verification.json`. Python fixtures use CPU images, temporary journals, synthetic credentials and local HTTP transports. Android tests exercise actual API/store/runner code with synthetic replies; they do not run a model or render.

| Local check | Result |
| --- | --- |
| Android JVM tests | **95 passed**, zero failures/errors/skips, including durable storage, legacy records, request authentication, recovery/retry/cancel and permission-state fixtures. |
| Python/router suite | **296 passed**, **13 subtests passed**, one Linux-only fixture skipped on Windows; 34.71 seconds. |
| Android compilation, lint and APK | Passed; lint reports zero issues. Version **0.3.1/code 4**, same application ID and signing certificate. |
| Notebook/source policy | Both cleared notebooks parse, all **17** router sources and pairing helpers match, both producers are deterministic; **28** static worker policy checks pass. |
| Integrity and reproducibility | All **124** checkpoint files and the frozen 0.3.0 folder/ZIP are hash-checked. Delivery sources are rebuilt once in a separate directory; copied/archived delivery files are hash-checked. |

The first Android check caught two indentation lint errors; they were corrected without a lint suppression. The final source-bound run includes the additional Generate and historical-record recovery guards. Earlier attempts are retained as separate evidence and are not the final acceptance result.

The fresh source-copy check rebuilds the APK offline from the exact delivery source inventory, regenerates both notebooks twice and reruns all 28 worker source-policy checks. No notebook cells execute. Its separate evidence is `source-rebuild.json`. Every delivered file and archived manifest entry is compared by SHA-256; the archive passes ZIP CRC checks. Earlier frozen bundle and pre-edit backup hashes are verified separately.

Recheck current artifacts in the original workspace:

```powershell
& '.\.work-router\test-venv\Scripts\python.exe' '.\.work-router\verify_extensive.py'
```

Fresh bounded checks, when sources change:

```powershell
& '.\.work-router\test-venv\Scripts\python.exe' '.\.work-router\run_extensive_checks.py' router
& '.\.work-router\test-venv\Scripts\python.exe' '.\.work-router\run_extensive_checks.py' android
```

These workspace runners use the existing private local SDK/cache paths and dependencies. In an extracted source tree, build with the included Gradle wrapper and an installed JDK/SDK; install the pinned `tests/router/requirements-dev.txt` into a separate environment for Python tests. The shipped source includes both notebook producers and the public resources needed by the static worker checker.

## Exact startup and remaining live checks

Follow [RECOVERY_STARTUP.md](RECOVERY_STARTUP.md) for exact settings, cell order, memory/error diagnosis and the approximately 12 real-adapter acceptance cases. The short sequence is:

1. Install the code-4 APK as an update; do not uninstall or clear app data.
2. Upload the cleared worker notebook into a fresh copy. Retain its existing persistent folder, checkpoint, Secrets and worker ID; keep `COMPATIBILITY_MODE=True`. Start one worker and require decoded warm-up plus authenticated health. Reveal its private setup code.
3. Upload the cleared router notebook. Paste one private worker code per line into `PHONE_STUDIO_WORKER_CODES`, or leave it empty to retain the legacy JSON list. Retain the same router storage and credentials. Run configuration, bounded prebuilt setup and the real adapter smoke cells before serving. Do not rerun passed smoke cases as another campaign.
4. In the app open Connect, scan the router's private Phone setup QR or paste its code, review the address and connect. Manual setup remains available. For a changed URL repair the existing connection ID after local waiting stops; preserve accepted-job recovery details.
5. Complete actual LLM enhancement/edit-plan/ranking cases, one unchanged Balanced generation and one manual-mask edit. Then add the other workers and verify a three-worker generation, reconnect recovery and one targeted third-worker restart/rejoin. Compare exact failure stages and runtime identities; never resubmit successful or uncertain accepted work.

No phone/emulator or permitted live notebook was available here. Actual installation/data retention, camera/permissions, accessibility/layout/font/rotation/animation, foreground-service lifecycle, real 4B quality/latency and RAM/VRAM headroom, SDXL generation/editing and three-worker recovery remain pending. The one Linux process-group fixture is skipped on Windows. The original RAM hypothesis is unproven and the historical intermittent worker failure remains unreproduced. Mock replies, static QR matrices and successful APK builds do not establish runtime success.

Only the plan's pinned 9B fallback is available, explicitly gated on indispensable 4B quality failure after one targeted correction. It is not an automatic response to loader, authentication, memory or timeout failure. Stop after the baseline live acceptance passes; optional acceleration remains off.

## Rollback

The pre-follow-up checkpoint is `.work-router/post-delivery-backup-20261009T055938Z/`. Its `manifest.json` lists **124** backed-up public files, including the preceding 0.3.0 APK. The current verification report lists changed and added files. This checkpoint contains code/artifacts only; it is not a backup of private app/runtime data.

When work is idle, stop only owned app/notebook work. Verify each checkpoint file against its manifest, restore changed source/notebook/producer/document files at the same relative paths, and move added files aside using the current report's inventory. Restore app and embedded notebook sources together. Preserve credential files, saved connections/library/drafts, journals, assets and model caches. Keep frozen deliveries intact.

Android normally blocks a code-3 APK over code 4. Keep the existing signing key and rebuild backed-up app sources with a code above 4, or deliberately use `adb install -r -d` with the backed-up debug APK on a connected device that supports a data-preserving downgrade. Neither device procedure was run here. Do not uninstall to bypass the version check. Restoring source alone does not downgrade an installed app. New serialized recovery fields have defaults and do not replace existing stored identifiers, but the older app lacks these additional guards; complete unresolved recovery before downgrading.

Older backend and UI rollback checkpoints are documented in [RECOVERY_STARTUP.md](RECOVERY_STARTUP.md) and [APP_REFRESH.md](APP_REFRESH.md).
