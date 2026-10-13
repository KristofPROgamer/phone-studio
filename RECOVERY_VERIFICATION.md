# Repaired files and scoped verification — 8 October 2026

This records the October 8 backend checkpoint. The October 9 app/QR update changes the app, notebooks and pairing helper; its current source-bound verification and rebuilt APK are in [APP_REFRESH.md](APP_REFRESH.md). Counts and hashes below retain their original checkpoint scope.

**Local repair complete; live acceptance pending.** The full existing/expanded router suite passed **184 tests, 13 subtests**, with **1 skipped**, in **29.17 seconds**. The skip is the real Linux process-group cleanup fixture on this Windows host. These are CPU/image fixtures and local HTTP mocks; they do not establish real inference, CUDA compatibility, semantic quality, speed or phone operation.

At this checkpoint the app/APK was unchanged. For the current notebooks and 0.3 APK, follow [RECOVERY_STARTUP.md](RECOVERY_STARTUP.md) and the app-update rollback in [APP_REFRESH.md](APP_REFRESH.md).

## What changed

- Corrected all adapter tasks to `response_format.json_schema.schema`, matching the pinned llama.cpp parser. The mock now rejects the old shape. Output validation, image payloads, request text, candidate coverage, cancellation and deadlines remain intact.
- Made the exact 4B Q4_K_M/matching f16 pair authoritative in `router/model_profile.py`. The sole pinned 9B fallback requires explicit confirmation of demonstrated essential quality failure; no automatic selection/download exists.
- Added safe inference categories and metadata logs. Health separates `processReady` from inference status. A failed/unvalidated task now sets existing `ready=false`, allowing the unchanged phone to display the safe failure message instead of “Assistant ready”; a validated success restores readiness. An initially untested reachable process retains initial readiness with explicit `inferenceStatus=untested`.
- Made prebuilt setup validate staging before atomic publication, check executable/dependent files/symlinks, retain bounded probe logs, preserve unknown directories and use exclusive setup locks. Complete owned-session/model/settings/integrity fingerprints control reuse before fresh VRAM admission. Failed/interrupted launches clean only their owned process; automatic CPU retry stays off.
- Added worker compatibility mode: ordinary PyTorch attention, no optional T4/Sage installation, no automatic/Comfy compilation, no approximate denoising/conditioning or experimental FP16 settings. Saved phone acceleration cannot override it. Cache/transport settings and SDXL checkpoint/presets remain.
- Fixed ComfyUI source identity and protected the exact existing Torch/CUDA stack with wheel-only dependency preflight. The revision `58b176f0c8427b1e3b1e0174ded3a7794641388b` is source/interface inspected, **not live validated**. Unknown/modified checkouts and user nodes/files are preserved. Owned symlinks can rejoin on a rerun; unknown additions still conflict.
- Repaired concrete shared-writer risks with finite first-preparation locks, UUID staging and instance-local atomic bridge publication. These source fixes do not prove the workers historically shared storage or explain every intermittent failure. Warm-up now authenticates the expected owned launch/runtime before dispatch and refuses unrelated port owners.
- Preserved independent completed health results when a third worker is slow, marked timeouts/stale observations separately, and passed bounded worker identity/effective-option/memory diagnostics through health. Explicit phone refresh now reaches uncached worker catalogs; routine probes stay cached.
- Protected accepted-result recovery through retrieval, persistence and observer failures. Durable accepted output skips rendering/history on retry; known accepted IDs are followed, and unknown acceptance blocks resubmission. Current persisted state and legacy accepted records are handled conservatively. Runtime identity must match before collection. Completed workers, assets and frozen edit preparation remain untouched.
- Added actual-adapter text/image/four-image acceptance helpers and separate host RAM/cgroup/process/GPU samples. Router and worker notebooks, producers, embedded helpers/hashes, tests and current instructions are synchronized. Optional SAM is off for baseline manual selection; Fooocus stock fallback and separate Drive reserve remain.
- Final verification also repaired direct-script imports, checked exported URL/key/degraded state before session reuse, retained safe per-call failure diagnostics in acceptance reports, and used the process's effective accessible cgroup ancestor limits for RAM admission. Missing bounds cannot authorize a CPU projector retry.

Protocol version 2, saved credentials/data/drafts, router state/accepted IDs, prepared edit assets, recovery/retry keys, checkpoint/LoRAs, 24/18 steps, canvas choices, seeds and negatives remain preserved. Frozen bundles were not edited. No weights, new GPU stack, native CUDA build or Android rebuild were performed locally.

## Evidence

Fresh evidence is `.work-router/recovery-verification-2026-10-08/verification.json`, with final source/notebook SHA256s, changed/added-file inventory, run timestamps/command/exit code, backup verification and test scope. The test log and fresh XML are `router-tests.log` and `router-tests.xml`; `test_run.json` binds the run to source hashes. Worker policy/source review has **28 passing checks** in `worker_source_review.json`. Both notebooks have parsed code, unique IDs, cleared outputs and exact helper/source matches; all **16 router embedded files** match active sources. The router producer generates identical bytes twice into temporary outputs; the worker producer was also checked for repeatability.

The full test command used the existing environment without upgrades:

```powershell
& '.\.work-router\test-venv\Scripts\python.exe' -m pytest tests/router -q -p no:cacheprovider --junitxml='.\.work-router\recovery-verification-2026-10-08\router-tests.xml'
```

The fresh source/hash report can be regenerated without notebook/GPU execution:

```powershell
& '.\.work-router\test-venv\Scripts\python.exe' '.\.work-router\verify_recovery.py'
```

Pinned artifact metadata evidence is `.work-router/recovery-model-metadata-20261008.json`. Worker upstream/interface evidence is `.work-router/recovery-worker-evidence-20261008.json`. Neither report verifies downloaded weights or runtime inference. October 1 Android build/lint/unit evidence remains historical; the unchanged APK SHA256 is `7a18f2419680a38753c0e1ad10e0fcf85e91870bfe54f0bfdc949a5b9ec90974`. Older aggregate scripts/reports are not fresh end-to-end evidence.

## Acceptance status

| Area | Status and limit |
| --- | --- |
| Schema/model identity, setup retry/integrity/reuse/cleanup | Passed locally with mocks/tiny fixtures; Linux cleanup fixture skipped. |
| Worker compiler/optional-install policy, safe bootstrap/rejoin | Passed locally; actual dependency install, preserved custom-node startup and decoded warm-up not tested. |
| Slow-third health and fresh catalog | Passed locally through real asynchronous/loopback transport with synthetic endpoints. |
| Generation/edit orchestration, exact zero-mask preservation | Passed locally using CPU image fixtures/mock workers; real SDXL generation/editing not tested. |
| Partial failure/retry/reconnect contracts | Passed locally; third-worker fault/rejoin preserves two completed records/assets and only retries confirmed failure. Accepted-result copy/follow, legacy records and post-acceptance persistence/observer failures are covered without a second render submission. Uncertain acceptance remains protected. |
| Direct startup commands, session exports and effective RAM bounds | Passed locally with isolated subprocesses and synthetic session/cgroup fixtures; real runtime reuse and memory measurements remain pending. |
| Actual 4B text/image/edit-plan/four-image ranking | Not tested: accessible permitted live runtime unavailable. |
| Host RAM versus VRAM cause, actual placement/headroom/latency | Not tested; original insufficient-RAM hypothesis remains unproven. |
| Phone one-worker generation/manual edit and full three-worker deployment | Not tested; no connected Android device or reachable worker configuration. |
| Historical intermittent worker failure | Unreproduced; live per-stage comparison and isolated restart/rejoin remain required. |
| Optional SAM/Fooocus | SAM off by default; guarded manual/stock contracts preserved and tested locally. Optional live feature inference not tested. |

The only local GPU observed was a Windows **RTX 2060 SUPER, 8192 MiB**; it is outside this repair's selected Linux T4 deployment. No accessible Colab tabs, private runtime credentials, local listening router/LLM/worker services or connected phone were present. No substitute deployment/model campaign was started.

Remaining live work is exactly the bounded sequence in [RECOVERY_STARTUP.md](RECOVERY_STARTUP.md): inspect two actual adapter smokes, run the full four-image case plus remaining approximately 12 semantic cases, confirm matching-session reuse and separate memory headroom, complete one Balanced phone generation and one manual-mask edit, then one three-worker generation/reconnect and isolated third-worker rejoin. Do not repeat passed or uncertain accepted work. Stop after the baseline passes; optional acceleration/source builds remain deferred.
