# Phone Studio 0.3.2 — 9 October 2026

The app and notebooks have been updated. Install `app/build/outputs/apk/debug/app-debug.apk` **over the existing app** to keep its saved connections, library, drafts and accepted jobs. This is a rebuilt debug APK, version 0.3.2/code 5, application ID `app.phonestudio`, Android 8/API 26 or newer. Do not uninstall or clear app data to update it. The current audit, results and rollback checkpoint are in [SECOND_AUDIT.md](SECOND_AUDIT.md). Earlier 0.3.0 and 0.3.1 bundles remain intact.

## Easier connection

1. Upload the current cleared worker notebook. Keep the existing checkpoint, Drive folder, Secrets and `COMPATIBILITY_MODE=True`. Give each copy its stable friendly `WORKER_ID`/`WORKER_NAME`; when switching an existing deployment to codes, use the exact existing JSON worker IDs.
2. After decoded warm-up and authenticated health, reveal its private worker code. Paste one code per line into the router's `PHONE_STUDIO_WORKER_CODES` Secret. It is the complete list of one to three workers. Leave it empty to keep the existing `PHONE_STUDIO_WORKERS_JSON` path.
3. Start the current router notebook with the existing ngrok account settings. Existing router password/token Secrets remain supported. Missing values are generated once and stored privately in the same persistent router folder. You do not need to type these values into the phone.
4. Finish the real assistant smoke checks, then start serving. In the app's **Connect** tab, tap **Scan QR** and scan the router's private Phone setup output. If the notebook is on the same phone, use **Paste code** instead. Review the name/address and tap **Connect**. Manual setup is still available.

QR generation is local to the notebook. The scanner decodes frames on the phone without a scanning app or Play services; it requests camera permission only when you tap Scan QR. A declined/unavailable camera or failed optional QR preview leaves the paste-code path. Codes contain existing credentials: keep outputs private and clear notebook outputs before sharing. They do not weaken authentication or create public credential links.

For a changed router URL, scan/paste its new code when the app's render is idle; the existing saved connection ID is retained. For one worker rejoin, retain its ID, replace only its code line, interrupt idle router serving, rerun **configuration**, then rerun **serving**. Keep the model and smoke cells untouched. Do not reset saved state or repeat successful/uncertain accepted renders.

Detailed runtime requirements, bounded assistant acceptance, phone generation/editing and targeted worker recovery remain in [RECOVERY_STARTUP.md](RECOVERY_STARTUP.md). Account/tunnel limits and required permitted runtimes still apply; QR pairing does not provision or automatically discover remote workers.

## App improvements

- A calmer blue-gray/lilac theme, clearer type, larger controls and softer tab/selection/expand transitions. Standard Compose motion follows the system animation setting.
- Prompt/edit canvas, results and recovery actions come first. Render settings, assistant preferences and previous connections open when needed.
- Tab scroll/search/disclosure state is retained. Library search covers prompts, models and seeds; filters separate generated images, edits and selected/all versions. Image details include prompt copying and the existing edit/export/settings tools.
- Model search, a compact download form and a visible refresh state. A failed refresh keeps saved choices and reports failure.
- First-time setup opens Connect. Compact connection/worker status, initial bounded discovery, no stale old-connection result overriding new settings, and an untested assistant is labeled as connected but unchecked.

The audit also fixed duplicate download starts, stale worker status after disconnect/removal, cancellation swallowed by optional work, credential encryption reporting, and credential durability before saved IDs are published. Active jobs prevent access-changing/removal/disconnect edits until stopped or finished. QR imports retain the router ID used by existing images and accepted jobs.

Unsupported studio-token header characters are rejected with a safe message before saving/requesting; existing bytes are not silently rewritten. Historical image requests have the same protection. Proxy/HTML error bodies are not echoed into app notices. Automatically generated credentials use ASCII. Supported custom passwords retain Latin-1 encoding and exact spaces across notebooks, phone and server. Unsupported characters fail safely before publication or GPU setup; existing credential files are retained. Requests capture their credentials with their endpoint, so changing saved settings cannot mix an old request with a new password.

## Historical 0.3.0 verification

The following results identify the preceding frozen 0.3.0 delivery. Current source-bound 0.3.1 results are in [EXTENSIVE_VERIFICATION.md](EXTENSIVE_VERIFICATION.md).

- **64 Android JVM tests passed**, zero failures/errors/skips, including strict setup parsing, saved-ID/active-job guards, error privacy, and the exact Python-generated QR matrices decoded by the phone's ZXing implementation.
- **249 CPU/router tests and 13 subtests passed**, one Linux process-group fixture skipped on Windows, in 42.53 seconds. Tests include existing generation/editing/recovery contracts and private-code/credential preparation under synthetic Secrets.
- Android Kotlin/resources compile, lint and debug APK packaging passed. The final lint report has no issues. The APK signature is checked against the pre-update APK before delivery.
- **28 worker source-policy checks passed**. Notebooks are cleared/parsed, embedded helper hashes match, and the router has **17** exact embedded files. The pinned 4B pair, prebuilt/no-compile defaults, SDXL settings and protocol 2 remain unchanged.

Historical evidence is `.work-router/app-refresh-verification-2026-10-09/verification.json`, including source hashes, commands, timestamps, exit codes, test/lint counts, APK identity/signature comparison, backup checks and changed/added-file inventory. Logs and source-bound run metadata are in the same folder. Recheck the current artifacts without running notebook/GPU cells:

```powershell
& '.\.work-router\test-venv\Scripts\python.exe' '.\.work-router\verify_extensive.py'
```

Only ZXing core 3.5.3 was added to the existing Android stack; no toolchain/dependency upgrade was performed. QR preview optionally uses the publisher's pure-Python [qrcode 8.2 SVG support](https://pypi.org/project/qrcode/8.2/), with a bounded, no-dependencies wheel install and paste fallback. The new tests use public synthetic credentials only.

No phone or emulator was connected. Actual camera permission/scanning, UI layout/animation at device font sizes/rotation, install/data retention, real 4B inference, GPU memory headroom, SDXL generation/manual editing and live third-worker rejoin remain untested. The Windows local GPU is not the selected Linux deployment. Local tests and QR matrices do not establish live runtime success or visual quality. The historical RAM and third-worker causes remain unproven/unreproduced.

## Rollback

For 0.3.2 use the matching 0.3.1 checkpoint and procedure in [SECOND_AUDIT.md](SECOND_AUDIT.md). The following instructions concern earlier updates.

For the 0.3.1 follow-up, use `.work-router/post-delivery-backup-20261009T055938Z/` and the exact procedure in [EXTENSIVE_VERIFICATION.md](EXTENSIVE_VERIFICATION.md). It restores the preceding 0.3.0 checkpoint. The older instructions below describe the initial UI update only.

The pre-update checkpoint is `.work-router/app-refresh-backup-20261008T205128Z/`; `manifest.json` lists **108** verified backed-up files, including the previous APK. The final verification report lists files changed/added by this update. Preserve credentials, library/drafts, job journals, assets, model caches and frozen bundles.

When work is idle, stop only this update's owned processes. Verify backup hashes, restore changed source/notebooks/producers/docs at the same relative paths, and move update-only files aside using the inventory. Restore the app's source/version and both notebooks together. The older backend-repair rollback is separate and is documented in `RECOVERY_STARTUP.md`.

The new APK has the same signing certificate as the previous APK. Android normally blocks installing its older version code over code 3. **Do not uninstall to bypass this:** either rebuild the backed-up app sources with a version code above 3 while keeping the existing signing key, or use a deliberate debug downgrade that preserves data (`adb install -r -d` with the backed-up APK) on a connected device that supports it. Neither device path was run here. Restoring sources alone does not downgrade an installed app.

The generated private router credential file remains part of persistent runtime state; do not delete it to clear an error. Returning to the original manual Secrets/JSON path requires retaining the same actual credentials and stable worker IDs. Do not mix old embedded sources with new model/projector defaults.
