# Repaired baseline and easier setup — 9 October 2026

Use the updated **PHONE_STUDIO_COLAB.ipynb** and **PHONE_STUDIO_ROUTER_COLAB.ipynb** in this workspace. Upload the cleared files into fresh notebook copies; older open copies can retain stale cells, imports and variables. The original repair record is `RECOVERY_VERIFICATION.md`; the app/pairing changes are in [APP_REFRESH.md](APP_REFRESH.md), and current follow-up evidence is in [SECOND_AUDIT.md](SECOND_AUDIT.md). GPU inference and phone operation remain pending until the sequence below passes.

The protocol, checkpoint, LoRAs, 24/18-step presets, canvases, seeds, negatives, saved data and accepted-job recovery remain the same. Install the rebuilt **0.3.2/code 5 APK as an update** to use QR scanning and the refreshed UI; keep the same app data and existing credentials. Older apps retain manual connection support. Password spaces are significant. Existing Basic authentication supports Latin-1 visible text; unsupported characters fail with a safe error and preserve saved files. Generated credentials use ASCII.

## Start one worker, then the assistant

1. Use an already permitted Linux GPU runtime. Start with the historically unreliable worker if identifiable. Leave healthy workers and accepted jobs running. Keep its existing Drive folder, checkpoint and Secrets. Do not delete model caches, custom nodes or credential files.
2. Upload `PHONE_STUDIO_COLAB.ipynb`. Leave **COMPATIBILITY_MODE=True**. Give each copy its friendly, stable `WORKER_ID`/`WORKER_NAME` (worker-1, worker-2, worker-3); for an existing deployment retain each exact `workerId` from its current JSON. These labels are not passwords. Run cells top to bottom. Native T4 attention, SageAttention, automatic compilation, approximate denoising/conditioning and experimental FP16 options are effectively disabled. The saved phone acceleration switch cannot override this mode. Ordinary PyTorch attention and local model/output caches remain available.
3. Worker bootstrap uses a fixed ComfyUI revision and preserves the installed Torch family/CUDA identity. An unknown, changed or incompatible checkout is preserved and rejected with a concrete conflict. Do not blindly pull, upgrade Torch or erase custom nodes. The pin is source/interface checked; GPU compatibility still needs the warm-up below.
4. Wait for **Warm-up complete**, including a decoded output, then authenticated worker health. Reveal and copy its private worker setup code. Existing worker credentials are reused; missing ones still follow the worker's saved credential preparation. A local successful health check followed by remote failure points to tunnel/address/authentication, not CUDA.
5. Upload `PHONE_STUDIO_ROUTER_COLAB.ipynb` to the separate Linux x86_64 T4/SM75 runtime, Python 3.11+, glibc 2.38+. Provide `NGROK_AUTHTOKEN` and grant notebook access. Existing `PHONE_STUDIO_TOKEN` and `TUNNEL_PASSWORD` Secrets remain supported; if missing, they are generated once and saved privately in the persistent router folder. `TUNNEL_USER` defaults to `studio`; `NGROK_DOMAIN` is optional where account defaults are usable.
6. Add the private worker code to `PHONE_STUDIO_WORKER_CODES`, one code per line. Start with one worker; the nonempty code Secret is the complete list of one to three workers. Do not rename existing IDs or share the codes. Alternatively, leave that Secret empty and keep `PHONE_STUDIO_WORKERS_JSON` unchanged, with its existing `workerId`, `name`, `serverUrl`, `tunnelUser`, `tunnelPassword` and `studioToken` entries. Keep a private copy before changing either configuration. Codes use final HTTPS addresses; legacy JSON retains its supported loopback HTTP case.
7. Run router cells in order. Leave `USE_PREBUILT_SERVER=True`, `ALLOW_SOURCE_BUILD=False`, `CPU_PROJECTOR_FALLBACK=False`, `AUTO_SEGMENTATION=False`, and `RUN_LLM_SMOKE=True`. The model cell validates official b11146 before downloading only the pinned 4B GGUF and matching f16 projector. The pair totals 3.148 GiB; an 8 GiB disk reserve remains. Archives/extraction require separate space.
8. The next cell performs **two actual calls through the application's LLMClient**, using a short count/relationship prompt and a tiny image edit plan. It saves expectations, outputs, timings and host/GPU samples privately in `/content/phone_studio_llm/adapter-smoke.json`. Inspect the output against the expectations: valid structure alone does not prove quality. Stop at the first failure and diagnose its category before rerunning.
9. Run the serving cell. It selects 8080, 8082, 8083 or 8084 and tunnels that same port; 8081 stays private. In the updated app's **Connect** tab, choose **Scan QR** or **Paste code** from the router's private Phone setup output, review its name/address, then tap **Connect**. Camera access is requested only for scanning. Manual setup remains available. QR generation stays local and has a bounded optional install; failed preview still leaves the paste code. Health distinguishes reachable process, last inference and individual worker timeouts. No inference is run by health polling.

A matching authenticated LLM session reuses its process before fresh memory admission, without another weight download/load/build. Rerun setup once after successful acceptance to confirm reuse. A different model/settings/integrity or an unrelated port owner is a conflict, not permission to kill it. To change one worker's URL/Secret, wait until idle, interrupt the router serving cell, update only that entry in the Secret, rerun the router configuration cell to refresh its worker settings, then rerun the serving cell. Leave the model and smoke cells untouched; the LLM and same state folder remain available.

## Bounded assistant acceptance

The two smoke calls count toward the plan's approximately 12 cases. After inspecting them, run the commented **four-image-only** call in the smoke cell once:

```python
await run_checks(Path(LLM_RUNTIME) / 'four-image-review.json', four_image_only=True, pids=(_llm_pid,))
```

This uses the actual source plus three synthetic candidates; the obvious expected winner is `changed-target`. It consumes no SDXL generation. Save image-dependent reasoning and all three scores. Continue the remaining cases through the same real adapter, reusing existing images. Use this expected-result sheet before reading responses:

| Cases | Expected result |
| --- | --- |
| Enhancement 1 (smoke), 2–4 | Preserve explicit count/relationship, named subject/style and exclusions; preserve long text or explicitly reject oversized context without truncation. |
| Edit plan 1 (smoke), 2–4 | Local refinement/replacement, whole-image change and directional outpaint; approved mode, bounded strength, valid normalized regions/margins; original intent retained. |
| Review 1 (four-image), 2–4 | Full source-plus-three preservation case, obvious count mismatch, obvious relationship mismatch, same unambiguous set reordered; complete IDs/scores, correct obvious winner and image-dependent reason. |

The script is also callable from an initialized runtime with its existing private LLM environment:

```text
python tools/llm_acceptance.py --report /private/adapter-smoke.json --pid LLAMA_PID
python tools/llm_acceptance.py --report /private/four-image-review.json --four-image-only --pid LLAMA_PID
```

Do not repeat already-passed smokes as an extra campaign. Each call retains the existing 180-second cap including serial waiting and the job deadline. One diagnosed correction/rerun is allowed; a repeated same-cause expensive failure stops that branch.

Before/after load samples are `/content/phone_studio_llm/memory-before-load.json` and `memory-after-load.json`. The acceptance reports sample host MemAvailable, per-process RSS/high-water/swap, process-cgroup and accessible ancestor limits/current/peak/OOM counters, and GPU free/used memory separately. Supply known notebook/router/LLM/SAM PIDs to the diagnostic helper where applicable; unavailable counters are null. Shared/file-backed RSS must not be summed as physical RAM. These are observed samples, not exact allocator peaks. A practical target is approximately 2 GiB T4 VRAM headroom without host exhaustion or swap thrashing. The preflight estimate is provisional, not a measured minimum.

HTTP rejection with stable memory suggests a protocol/template/context problem. CUDA allocation failure with exhausted VRAM supports GPU pressure. Collapsing host memory plus OOM-event increments supports host exhaustion. Exit -9/137 alone proves neither. Deadline, queue wait, incomplete output, malformed JSON and invalid task fields have separate diagnostics. Do not reload the old 27B merely to investigate past failures.

Keep 4B if essential cases pass. Only if it loads/runs stably but fails indispensable quality after one targeted prompt correction, unload it and explicitly select `model_profile='9b', quality_fallback_confirmed=True` in setup. The sole fallback is the audited pinned 9B pair; do not download it upfront or use it for loader/authentication/memory failures. Preserve the 8K serving policy and validate the same cases.

## Phone generation, editing and the third worker

1. Through the phone, complete one **Balanced generation** with the unchanged checkpoint. Inspect original/effective prompt, returned image/settings and persistence after reopening.
2. Complete one **Paint area/manual-mask edit** with the same checkpoint. Verify edit method, source lineage, retained candidates and exact preservation outside the normalized mask. Automatic SAM remains an optional guarded feature; a manual mask still requires a working LLM edit planner. Generation can retain original prompts and unreviewed candidates when the assistant fails.
3. Add the other two existing workers only after the one-worker path passes. Verify distinct authenticated runtime IDs and notebook/bridge fingerprints, intended checkpoint availability, effective optional flags and both local/remote health. An explicit catalog refresh now reaches uncached inventories; routine preflight stays cached.
4. Run one three-worker generation. Retain all actual candidates and accepted prompt IDs, then verify actual image-based ranking. Background/reconnect the phone and confirm it resumes the same job ID without duplicate accepted renders.
5. If the third worker fails, compare its exact stage with the healthy two: setup, warm-up, tunnel, readiness/catalog, dispatch or retrieval. Record redacted runtime/version/memory/storage/checkpoint/credential-match facts. Never resubmit successful or uncertain accepted work. Retry only through the existing targeted retry key: confirmed execution failure may render again, while a known accepted result with a follow/copy failure retains its IDs and only follows/downloads that same result. Matching authenticated runtime identity is required; unavailable/restarted identity preserves the records for diagnosis. Review only actual available candidates.
6. When idle, restart/rejoin only that worker once with the final notebook. Keep the other workers and LLM running. Check its new runtime ID. If its connection entry changed, interrupt the idle router serving cell, update only that Secret entry, rerun router configuration, then rerun serving. Leave model and smoke cells untouched. Use existing warm-up or one targeted request; do not rerun the full three-worker suite.

The historical intermittent failure is unresolved until this live comparison/rejoin passes. Source-confirmed health/catalog defects have been repaired, but they do not establish the cause of every third-worker failure. Shared Drive race hypotheses apply only when the instances actually share storage; different VMs legitimately reuse localhost ports and paths.

## Rollback

For the October 9 app/pairing update, use the matching backup and APK procedure in [APP_REFRESH.md](APP_REFRESH.md). The steps below concern the preceding backend repair; its older file inventory does not cover the app update.

The verified pre-repair source backup is `.work-router/recovery-backup-20261008T143813Z/`, with SHA256s in `manifest.json`. The extra verification fixes also have a small pre-edit checkpoint in `.work-router/reverification-backup-20261008T202228Z/`. The final changed/added-file inventory is in `.work-router/recovery-verification-2026-10-08/verification.json`.

Wait for or deliberately cancel accepted work through the existing mechanism before rollback. Stop only idle processes owned by this repair. Verify backup hashes, then restore the changed source, notebook, producer, test and documentation files from their matching relative paths in the backup. Move added repair-only files aside using the inventory; do not remove job journals, assets, prepared edits, Secrets, caches or frozen bundles. Restore notebook/default/profile together. The old 27B has its original resource demands and is a historical rollback, not the recommended baseline. Reconnect to the actual router URL and verify provenance after restart.

For a runtime rollback, upload the matching backed-up notebooks into separate cleared copies. Do not mix old embedded sources with new model/projector defaults, and do not reset persistent state to clear an error.
