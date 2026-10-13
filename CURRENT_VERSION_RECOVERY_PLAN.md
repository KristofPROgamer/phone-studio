# Phone Studio: make the current version work realistically

**Audited execution plan — 8 October 2026**  
**Intended executor:** GPT-6.1 Sol, Ultra thinking, as requested by the user. This document does not change the model of a chat or start implementation.

**Objective:** get the existing Phone Studio Android → router → image-worker workflow working reliably on the available, permitted hardware, with a substantially smaller local vision assistant and an ordinary startup path that does not compile CUDA extensions. Make only incidental improvements that directly remove a blocker, prevent recurrence, or make a failure understandable.

The user's scope correction governs every decision: **fix the current version, make it realistic, and do not spend excessive resources on improvements.** A working baseline is the stopping point. This is a repair project, not a performance research project.

## 1. Recommended decision

Keep the current architecture and protocol. Replace the default 27B assistant with **Huihui-Qwen3.5-4B-abliterated, Q4_K_M, with its matching f16 vision projector**, served by the existing pinned llama.cpp prebuilt if the actual runtime passes compatibility and inference checks. Its two artifacts total **3.148 GiB**, versus **11.999 GiB** for the current model/projector: approximately **74% less to download and store**. This does not establish a VRAM or speed improvement of the same percentage.

Use **one 9B model as a conditional quality fallback**, only if the 4B model starts successfully but fails essential application tasks. Do not download both upfront. Do not return to the 27B model merely because it once reached readiness.

Keep the router's existing prebuilt route and disabled automatic source fallback. Add a simple worker compatibility setting that bypasses native attention installation and automatic compilation. Retain the selected SDXL checkpoint, app interface, generation presets, saved data, worker orchestration, and editing pipeline.

**Latest user clarification:** the notebooks and app started, but classification/ranking and other LLM-dependent actions consistently failed. Frequently two worker notebooks succeeded while the third required rerunning or configuration changes. The user suspects insufficient instance RAM. Treat these as the actual repair targets; successful startup is not resolution. Host RAM pressure is a hypothesis, not an established cause.

The earlier chat reports that the prebuilt loaded the 27B model on a T4 and the router started after its port conflict was corrected. That is historical startup evidence only. The user's later report establishes that usable inference and consistent worker operation were still failing.

**An additional P0 defect was found after this clarification:** the router sends its JSON schema in the wrong field for the exact pinned server. Correcting this is required alongside the smaller model; replacing weights alone would leave the protocol defect intact.

## 2. What this audit establishes

This plan combines direct source inspection, three independent reviews, a fresh local CPU/mock test run, notebook source/hash checks, public model artifact metadata, and the relevant earlier chat, **“Speed up image generation.”**

| Evidence | Result and limit |
|---|---|
| Current router suite | **104 passed in 15.03 seconds** on 8 October, using the existing local Python environment. These are CPU/mocked tests. |
| Current router notebook | Valid syntax, cleared outputs, unique cell IDs; all **13 embedded source files** and embedded hashes match active source. |
| Current worker notebook | Valid syntax, cleared outputs, unique cell IDs; embedded T4 installer and editing helper match their source files. |
| Smaller model artifacts | Immutable repository revisions, filenames, sizes, and publisher-hosted SHA256 metadata retrieved. Weight files were not downloaded or independently hashed. |
| Prebuilt retry defect | Independently reproduced with tiny fake files and a mocked failed probe. The first failure leaves an unstamped final directory; the second attempt refuses it. |
| Historical startup | Earlier chat records prebuilt/T4 validation and LLM readiness, worker warm-up, leftover compilation, a port conflict, and insufficient RAM for automatic masking. No live session was inspected for this plan. |
| User's later operating report | Startup succeeded, but LLM features failed; worker startup/operation was intermittently two out of three. This supersedes any inference that earlier readiness meant the application worked. |
| Pinned server contract | Source confirms the adapter's schema wrapper does not match the server parser. This is a definite code defect and a plausible common cause of failed LLM tasks; historical root cause still requires a failed response/log. |
| Older verification reports | October 1 report hashes no longer match either active notebook. Its APK hash still matches. Treat its build/lint/device scope as historical. |
| Version control | The current workspace is **not a Git checkout**. Do not assume a clean branch, commit history, or automatic rollback is available. |

Machine-readable evidence and the inspected source hashes are in [audit_evidence.json](E:/small_phonecollabaiproj/.work-router/recovery-plan-audit-2026-10-08/audit_evidence.json). The collection helper writes only planning evidence and does not run notebook cells.

No GPU compilation, model download, model inference, current-runtime measurement, Android rebuild, or application change was performed to prepare this plan. Source references below describe the audited baseline; search by function or notebook cell ID if later edits shift lines.

## 3. Scope and resource rules

### Required work

1. Fix the LLM request/schema contract and replace the oversized default assistant while preserving native vision.
2. Make normal router and worker startup avoid optional CUDA/native-extension compilation.
3. Fix narrow setup/restart defects that directly obstruct that route.
4. Keep generated notebook content, source, metadata, and setup instructions consistent.
5. Validate cheaply locally, then perform a small real-runtime acceptance sequence.
6. Report supported, degraded, failed, and unverified behavior accurately.

### Preserve

- API/protocol version 2 and the app's saved router connection.
- The chosen image checkpoint and LoRAs; Balanced/Fast step counts, canvas choices, seeds, and negatives.
- Original prompts, all candidate images, image lineage, manual masks, and saved drafts.
- Request IDs, accepted-job recovery, prepared edit assets, uncertain-submission handling, and retry keys.
- Authentication, private loopback LLM binding, opaque asset IDs, and validated LLM output.
- Existing verified caches and source backups. Frozen `finished things/` bundles remain frozen.
- Existing optional acceleration implementation as explicit opt-in code, unless a demonstrated blocker requires a narrow correction.

### Excluded

No new model picker, UI redesign, generic configuration framework, database redesign, distributed scheduler, cloud-provider migration, engine migration, model training, quantization project, kernel optimization, broad dependency upgrade, or benchmark leaderboard. No paid provisioning or automatic deletion of large existing assets.

Do not change SDXL output settings to make the assistant replacement look faster. Do not lower resolution or sampling steps under the label of a reliability fix.

### Bounded effort policy

These are implementation guardrails, not promises about elapsed startup time:

- **Model search stops here:** one primary and one conditional fallback. Recheck their exact metadata before implementation; do not start a wider search without a concrete failure.
- **Normal route: zero source CUDA builds.** Do not extend the 90-minute build timeout again. Do not compile a replacement worker attention kernel to get a basic render.
- **One model loaded at a time.** Do not run the old and replacement assistants together to compare them.
- **One worker first.** Validate the router and one worker before spending resources on three simultaneous workers.
- **One small acceptance set:** approximately 12 assistant calls, two single-worker image jobs, then one three-worker generation. Reuse existing images for assistant tests.
- **One correction and rerun for a diagnosed failure.** After a second failure with the same cause, stop that expensive branch, record the specific blocker and next action, and continue independent cheap work. Do not keep restarting or downloading without a changed hypothesis.
- **Incidental improvements:** target no more than roughly 10–15% of implementation effort. A task qualifies only if it is adjacent to a required change, has a concrete failure/use case, and can be checked cheaply. This is a prioritization rule, not permission to ignore a correctness defect in changed code.
- Run the relevant existing tests once after coherent changes, and rerun affected tests after fixes. Do not repeatedly rebuild an unchanged APK.

## 4. Findings and required response

Priority **P0** means required for the repair path or honest acceptance; **P1** means a small directly related reliability fix; **defer** means leave it outside the working baseline unless evidence makes it necessary.

| ID | Priority / evidence | Finding | Required response |
|---|---|---|---|
| A01 | P0, confirmed source | Current weight/projector pair is 12,884,046,912 bytes. The GPU probe assumes 27B and requires 14,000 MiB total / 13,000 MiB free. | Replace the model/projector together; revise identity, budget checks, and messages together. |
| A02 | P0, confirmed source | Model identity is duplicated in setup, router configuration, and LLM adapter. | Keep one small authoritative profile or enforce equality. Update notebook embedding and provenance. |
| A03 | P1, reproduced | Prebuilt extraction is promoted before compatibility probes and stamp publication. A failed probe poisons ordinary retry. | Probe staging; publish a complete validated install atomically. Preserve unknown old directories. This is not the leading explanation for failed inference after startup. |
| A04 | P0, confirmed source | Workers can compile T4 attention, install SageAttention on newer GPUs, and use automatic compilation. | Add one ordinary-PyTorch compatibility path that bypasses all three routes. |
| A05 | P0, confirmed risk | Worker bootstrap clones/pulls moving ComfyUI and installs its current requirements. It may change the Torch stack despite later comments. | Pin one validated revision and constrain the existing matched Torch family; fail clearly on incompatibility. |
| A06 | P1, confirmed source | Probe errors can lose captured stderr; a generic message may reference a log that was never written. | Save bounded stage diagnostics and surface a concise reason with the actual log path. |
| A07 | P1, confirmed source | Prebuilt reuse hashes only the executable, not its dependent libraries; session reuse omits complete profile/settings identity. | Add small integrity and session fingerprints for the normal prebuilt/model route. |
| A08 | P1, confirmed source | Interrupting LLM loading can leave an owned process without a session record; any failure triggers CPU-projector retry. | Clean up only the process started by this attempt; avoid retries for non-memory failures. |
| A09 | P0, confirmed source | Four-image edit review and long text can approach/exceed the context budget. | Keep 8K initially; test a full source-plus-three-candidates call and explicit overflow behavior. |
| A10 | P0, confirmed source | Generation can degrade when the LLM is down; a new edit still requires `plan_edit`, even with a manual mask. | Do not advertise LLM-free editing. Preserve the current explicit failure unless a separate need justifies more work. |
| A11 | P1, historical + source | Automatic SAM selection previously lacked host RAM; Fooocus previously hit Drive reserve checks. | Preserve guarded/manual/stock fallbacks. Do not make optional setup block basic operation. |
| A12 | P0, confirmed source | Older aggregate verification trusts saved reports/XML, and some old source checks require experiments ON. | Update intended-policy checks and create fresh evidence tied to final hashes. |
| A13 | Defer, source + history | Opt-in source-build timeout can leave compiler descendants; no build-directory lock exists. | Keep that route disabled and label it unvalidated. Only repair it if retaining a supported source-build route becomes necessary. |
| A14 | P0, confirmed against pinned upstream source | Adapter sends the schema as a sibling of `type: json_schema`; server reads `response_format.json_schema.schema`. All tasks use this path. | Correct the wrapper before evaluating the replacement model. Add a mock that enforces the real server contract. |
| A15 | P0, confirmed source | LLM HTTP errors lose their status/reason; request failures become generic; health ignores the last inference failure. | Add bounded inference diagnostics and separate process readiness from verified usable inference. |
| A16 | P0, confirmed source | A single 4-second aggregate health deadline can cancel slower worker probes and discard a completed LLM health result. | Retain independently completed health results and mark individual timeouts; do not let a slow third worker invalidate the assistant's observed status. |
| A17 | P0, user report; root cause unresolved | Two workers often succeed and the third requires manual retry/switching. | Compare all three instances at the exact failure stage, repair the demonstrated difference/race, then validate an isolated third-worker restart without restarting the healthy two. |
| A18 | P1, confirmed source | The phone's explicit catalog refresh still sends `cached=1` to each worker; stale checkpoint/LoRA availability can survive for 300 seconds. | Pass fresh/cached intent through the existing catalog/probe functions. Preserve normal background/preflight caching. |

Concrete locations:

- A01/A02: [tools/router_setup.py:23](E:/small_phonecollabaiproj/tools/router_setup.py:23), [router/config.py:145](E:/small_phonecollabaiproj/router/config.py:145), [router/llm.py:18](E:/small_phonecollabaiproj/router/llm.py:18).
- A03/A06/A07: [prepare_prebuilt](E:/small_phonecollabaiproj/tools/router_setup.py:232); promotion at baseline line 271, probes at 277, stamp at 287.
- A07/A08: [session reuse](E:/small_phonecollabaiproj/tools/router_setup.py:392), [start_server](E:/small_phonecollabaiproj/tools/router_setup.py:412).
- A04/A05: worker cells `ZCZiRTxZ7chm` (compile default), `Wfao1hYr7chn` (bootstrap), `fdvY4gbkN6OV` (GPU settings/installers), `ELLSK7uo7chn` (bridge).
- A09/A10: [LLM completion](E:/small_phonecollabaiproj/router/llm.py:184), [visual review](E:/small_phonecollabaiproj/router/llm.py:322), [mandatory edit planning](E:/small_phonecollabaiproj/router/service.py:230).
- A11: [segmentation setup](E:/small_phonecollabaiproj/tools/router_segmentation_setup.py:140), [runtime notes](E:/small_phonecollabaiproj/RUNTIME_SETUP.md).
- A12: [.work-router/verify_stage.py](E:/small_phonecollabaiproj/.work-router/verify_stage.py:47), [.work-speed/create_final_source_review.py](E:/small_phonecollabaiproj/.work-speed/create_final_source_review.py:97).
- A13: [command runner](E:/small_phonecollabaiproj/tools/router_setup.py:39), [source build](E:/small_phonecollabaiproj/tools/router_setup.py:300).
- A14/A15: [request serialization](E:/small_phonecollabaiproj/router/llm.py:197), [HTTP error handling](E:/small_phonecollabaiproj/router/llm.py:168), [readiness](E:/small_phonecollabaiproj/router/llm.py:142).
- A16: [aggregate health](E:/small_phonecollabaiproj/router/service.py:139), [worker probe deadlines](E:/small_phonecollabaiproj/router/workers.py:78).
- A18: [catalog endpoint](E:/small_phonecollabaiproj/router/server.py:96), [catalog aggregation](E:/small_phonecollabaiproj/router/service.py:159), [always-cached worker request](E:/small_phonecollabaiproj/router/workers.py:81); worker bridge function `model_catalog`.

### The schema defect, precisely

Current adapter request:

```python
{"response_format": {"type": "json_schema", "schema": task_schema}}
```

Required shape for the pinned server:

```python
{"response_format": {
    "type": "json_schema",
    "json_schema": {"schema": task_schema}
}}
```

At the pinned commit, the server reads the nested wrapper and treats an absent schema as a generic object. Consequently, the task's required fields are not enforced. The current mock checks the format type but does not simulate this parsing, so its passing result misses the incompatibility. The upstream parser and upstream test agree on the nested form. [Pinned parser](https://github.com/ggml-org/llama.cpp/blob/7fe450e19305b828c199d602c23a8337aaa1f03b/tools/server/server-common.cpp#L1185-L1203), [pinned test](https://github.com/ggml-org/llama.cpp/blob/7fe450e19305b828c199d602c23a8337aaa1f03b/tools/server/tests/unit/test_chat_completion.py#L234-L251).

Fix the request; do not weaken response validation to accept arbitrary objects. Confirm actual behavior with one text and one image request through the real adapter.

## 5. Exact model decision

### Primary

Use `mradermacher/Huihui-Qwen3.5-4B-abliterated-GGUF` at revision:

```text
4a5daa6fbefca5fe822dc65fcb95cc4576fa9720
```

| Artifact | Bytes | SHA256 |
|---|---:|---|
| `Huihui-Qwen3.5-4B-abliterated.Q4_K_M.gguf` | 2,707,514,688 | `423f10b6ec2d99c3378143d7cd3b80eb4887b3ed92103103ac59173b404f4f7c` |
| `Huihui-Qwen3.5-4B-abliterated.mmproj-f16.gguf` | 672,423,552 | `f14643c11f1e8244c59bca670e2a4c843be4234aa6bb88d0647dae7297798686` |

Combined: **3,379,938,240 bytes / 3.148 GiB**. These identities were checked against [immutable artifact metadata](https://huggingface.co/api/models/mradermacher/Huihui-Qwen3.5-4B-abliterated-GGUF/revision/4a5daa6fbefca5fe822dc65fcb95cc4576fa9720?blobs=true).

This is a third-party quantization of Huihui's model; do not call the quantizer the original model publisher. The Huihui card describes a text-modified, non-thinking-oriented model with its image component retained. Its “abliterated/uncensored” description is a publisher claim, not a guarantee of zero refusals or retained accuracy. [Huihui model card](https://huggingface.co/huihui-ai/Huihui-Qwen3.5-4B-abliterated), [quantizer model card](https://huggingface.co/mradermacher/Huihui-Qwen3.5-4B-abliterated-GGUF).

The metadata declares `qwen35`, matching the architecture already targeted by this setup. That is a reason to try the existing engine first, not proof that this exact pair passes the server's vision and JSON workflows. Use the f16 projector to avoid adding a second quantization variable.

### Conditional quality fallback

Use only when the primary loads and runs correctly but fails indispensable task-quality checks after one targeted prompt/template correction:

```text
repository: mradermacher/Huihui-Qwen3.5-9B-abliterated-GGUF
revision:   9f646d7eda193ddf2348134f3bff3d49eed7a2c6
```

| Artifact | Bytes | SHA256 |
|---|---:|---|
| `Huihui-Qwen3.5-9B-abliterated.Q4_K_M.gguf` | 5,627,045,248 | `ea1858ef4dc4b648b8dbb44612962a0333e945060dd0545ac0f28d7c4416e4b3` |
| `Huihui-Qwen3.5-9B-abliterated.mmproj-f16.gguf` | 918,166,016 | `56f07ff42fc9ab24fc06a93dce5a48fb2dbe08bff1a1c6e519d50af450820148` |

Combined: **6,545,211,264 bytes / 6.096 GiB**. [Immutable artifact metadata](https://huggingface.co/api/models/mradermacher/Huihui-Qwen3.5-9B-abliterated-GGUF/revision/9f646d7eda193ddf2348134f3bff3d49eed7a2c6?blobs=true).

Do not use the 9B fallback to treat a missing library, incompatible driver, unsupported architecture, wrong template, or wrong projector. Diagnose that failure first. Both candidates share the same architecture family.

### Model integration details

1. Select the pair explicitly in setup; no dynamic “latest,” automatic model shopping, or silent fallback.
2. Reuse the existing verified downloader with revision-specific URLs, exact lengths, hashes, and atomic file promotion.
3. Store each pair under a profile/revision-specific cache directory. Never reuse the old projector because its filename looks generic.
4. Update the setup alias, router defaults, health identity, review provenance, documentation, and embedded source as one change.
5. Keep old review/job records unchanged. New results identify the new model; historical records retain their actual reviewer.
6. Preserve old files for rollback; exclude unrelated large caches from any new source backup. Do not redownload the old model.
7. A small shared constant/profile module is acceptable if it eliminates duplicate identities. A multi-backend plugin/configuration system is not.
8. Record license/base-model provenance with the manifest; recheck the pinned repository before downloading.

## 6. Execution sequence with gates

### Phase 0 — Preserve the current state and identify the actual runtime

**Local work can proceed immediately.**

- Read this plan and its evidence. Check for instructions added since the audit.
- Recheck source hashes. If the workspace changed, inspect the differences before applying planned edits.
- Since no Git checkout exists, make a small timestamped backup of files to be edited plus a SHA256 manifest. Include active notebooks, changed router/tools modules, notebook producers, affected tests, and current docs. Do not copy `.tools`, Python environments, build caches, image models, or frozen bundles.
- Record baseline test status. The fresh 104-pass result can be reused if relevant source/environment hashes are unchanged; do not rerun it merely to reproduce a number.
- Treat the active source tree as authoritative. Old patch scripts and frozen bundles are reference material.

**Before live work**, collect a small redacted runtime snapshot:

- OS, architecture, glibc, Python, GPU name/compute capability, driver, total/free VRAM, available host RAM.
- Runtime-local disk free space and actual persistent-storage capacity separately.
- Existing ComfyUI revision and Torch/torchvision/torchaudio versions where present; CUDA runtime reported by Torch.
- Existing server/worker processes, their known owner records, occupied relevant ports, and any leftover compiler jobs.
- Which worker addresses are currently reachable and have the intended checkpoint/LoRA.

Use read-only probes. Never print full environment variables, Secret contents, connection JSON, prompts, or private source images into a shareable diagnostic.

**Gate:** local files are recoverable; current runtime facts are either recorded or explicitly pending. Lack of live access blocks only live validation, not the local repair work.

### Phase 0.5 — Correct and expose inference failures before judging models

This is required work, not incidental optimization. Implement it locally before any new model-quality evaluation.

1. Correct A14's wrapper in the shared completion path. Test that all task schemas reach the nested server field; have the HTTP mock reject the old shape instead of returning valid results unconditionally.
2. Add concise failure categories: transport/authentication, server rejection, context overflow, inference deadline, incomplete output, malformed JSON, and invalid task fields. Preserve existing public fallback behavior.
3. Log request ID/task, image count and dimensions, schema/profile fingerprint, HTTP status, safe server error type/code, finish reason, output-token usage if supplied, reasoning-field presence/length, and preparation/queue/inference duration. Do not log credentials, input text, image data, or whole production response bodies. A controlled synthetic probe may save its known-safe reply privately. Never forward arbitrary upstream text to the phone.
4. Keep failed calls visible in health/status messaging. A responsive process advertising vision is not proof that a task succeeded. Expose a lightweight last-inference result or diagnostic readiness distinction using existing/additive fields; do not run inference on every health poll.
5. Add a cheap one-time or explicitly invoked functional smoke using the real `LLMClient`, one short text fixture and one tiny known image. Reuse two of the 12 acceptance cases, so this adds no separate evaluation campaign.
6. Repair A16's health aggregation: preserve completed worker/LLM results independently within bounded time. Do not increase every timeout blindly or let an unfinished third-worker catalog call reset assistant status.
7. Keep failure handling compatible with existing Android fields and protocol. A UI change is needed only if the existing message/degraded fields cannot communicate the actual failure.

For RAM diagnosis, record **host RAM and GPU VRAM separately** before loading, after loading, during the two smokes, and during the largest image call. Use host `MemAvailable`, process RSS/high-water/swap values, and effective cgroup memory limit/current/peak plus OOM-event deltas where accessible. Include the notebook/kernel, router, llama server and SAM when present. Shared/file-backed mappings must not be counted as independent physical RAM merely by summing RSS.

| Evidence around a failed call | Interpretation / next step |
|---|---|
| CUDA allocation failure plus exhausted device headroom | GPU-memory pressure; inspect model/projector placement and active jobs. |
| Host available memory collapses and OOM-kill counter/log increments | Host-memory exhaustion is supported; smaller weights/offload avoidance and optional SAM gating address it. |
| Exit -9/137 without memory evidence | Process was killed; cause remains unresolved. Runtime reclamation or external termination is also possible. |
| HTTP 400 or structured error with stable memory/process | Inspect schema, template, input budget and supported request fields. |
| HTTP 200 with missing task keys / incomplete finish reason | Inspect actual schema enforcement, template and output limit before changing hardware. |
| Only reasoning content, with empty final content | Diagnose thinking/template/parser behavior; never reinterpret reasoning as the final structured answer. |
| Deadline elapsed but process remains healthy | Separate time waiting for the serial slot, prompt/image processing and generation; do not assume OOM. |

Interpret memory counters using [Linux process-memory documentation](https://www.kernel.org/doc/html/latest/filesystems/proc.html) and [cgroup memory counters](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html). Record unavailable counters as unavailable. Separate worker VMs do not contribute their RAM to the router's limit; colocated processes do. Do not disable mmap, add swap, or move layers/projector to CPU without evidence.

Do not reload the oversized 27B model solely to diagnose the past. Use surviving logs if available, then apply the confirmed protocol fix and evaluate the smaller model. No evidence in this plan establishes which combination caused the historical failures.

**Gate:** the known schema mismatch is fixed and a future failed inference produces enough safe evidence to distinguish memory pressure from protocol/output errors.

### Phase 1 — Make the router's prebuilt path retryable and diagnosable

Files: `tools/router_setup.py`, focused setup tests, router notebook producer.

1. Keep `USE_PREBUILT_SERVER=True` and `ALLOW_SOURCE_BUILD=False`. Keep release **b11146**, commit **7fe450e19305b828c199d602c23a8337aaa1f03b**, unless a concrete incompatibility requires a different verified binary. The official release supplies separate CUDA server and runtime archives. [Official release](https://github.com/ggml-org/llama.cpp/releases/tag/b11146).
2. Check platform/glibc and GPU visibility before downloading weights. Preserve the existing private library directory. Do not replace system glibc, driver, Torch, or CUDA toolkit to force this binary to run.
3. Preserve archive size/hash validation and confined extraction. Validate staging with the exact private library path; collect `--version` and `--list-devices` output.
4. Create an installed-file integrity manifest for the executable and actual dependent library files/symlinks. Bind it to the archive hashes/release. Then publish the complete validated installation. Use a small exclusive setup lock so two notebook executions cannot publish into the same path.
5. Ensure a failed probe removes only this attempt's owned staging and leaves downloaded verified archives reusable. It must not leave a new unusable final directory.
6. For an already-existing unstamped release directory, preserve it and report a confined quarantine/recovery action. Recognize ownership before moving it. Never recursively delete an unknown directory to make setup pass.
7. Record bounded probe stderr/stdout, stage, return code, and timeout in a private log. User output should identify the stage and log path without exposing secrets.
8. Keep normal-route failure closed: a failed prebuilt must not invoke CMake, nvcc, a source checkout, or an implicit build.

**Gate:** tiny fault tests show failed-first-probe → successful retry, integrity failures remain visible, unknown directories survive, and no compile fallback occurs.

If a live runtime rejects the current binary, allow one evidence-based check for a compatible official prebuilt with pinned hashes. Do not cycle through arbitrary releases. If none is justified, finish local work and report the exact deployment blocker rather than beginning a source build.

### Phase 2 — Switch to the small assistant and make reuse truthful

Files: `tools/router_setup.py`, `router/config.py`, `router/llm.py`, optionally one small shared profile module, setup/adapter tests.

1. Install the primary model identity from section 5 into the selected profile; synchronize all consumers.
2. Initially retain **8192 context, one serial slot, batch 256, microbatch 128, f16 KV, image cap 1024, thinking disabled**, and the current image-preview limit. These bound risk while changing the model.
3. Do not reduce context to 4096: edit review includes the source and up to three candidates, before text and output. Do not silently omit images or truncate user instructions.
4. Replace 27B-specific resource messages and fresh-start admission checks with a selected-profile budget. Keep T4/SM75 as the initial supported target; expanding to older or smaller GPUs is outside scope.
5. Start with a conservative documented preflight estimate using artifact sizes plus explicit compute/context/headroom allowances. Label it provisional. Measure loaded/inference use before advertising a minimum. Do not claim file bytes equal required VRAM or retain the irrelevant 13,000-MiB free guard.
6. Preserve disk reserves initially; calculate required download space from the selected files and cache validity. Account for server archives/extraction separately. Do not lower every reserve as a substitute for measuring storage.
7. Record a session fingerprint: model repo/revision, GGUF/projector hashes, server identity, serving settings, port, and actual placement/degraded status. Check identity against the server's exposed model information where available.
8. A matching healthy session must be reused before the fresh free-memory check. A different model/profile must not be treated as a match. Return consistent model/server provenance on both fresh and reused startup.
9. Avoid duplicate server launches. For an old owned session with a different profile, stop it deliberately only when it is idle and its ownership is verified; otherwise provide a specific conflict. Never kill whatever happens to own port 8081.
10. Wrap startup waiting/publication in cleanup that handles timeout and interruption. Stop only this attempt's owned process/process group and preserve its log.
11. For the small default, disable automatic CPU-projector retry initially, or permit it only for demonstrated **GPU** placement pressure with adequate host RAM. Host OOM is not a reason to move more work onto CPU. Unsupported flags, loader failures, and missing libraries should fail once. Any retained CPU projector mode must pass latency checks and be clearly labeled degraded.

Keep schema validation, image payloads, finite scores, exact candidate coverage, cancellation, and the existing 180-second call deadline including serial-slot waiting. Adapt a model template or prompt only if a specific acceptance fixture demonstrates a need.

**Gate:** local tests prove selected identity consistency, mismatch rejection, same-session reuse, clean interrupted startup, and unchanged application contracts.

### Phase 3 — Give workers an ordinary, reproducible startup path

Files: worker notebook cells and any directly affected helper/source checks. Avoid an Android change.

1. Add one plainly named notebook setting, such as `COMPATIBILITY_MODE=True`, for the baseline. Compute requested versus effective flags in one place and show their reasons.
2. In that mode: T4 native attention installer is skipped, SageAttention installation/import is skipped, and `torch.compile` is off on every GPU family. Use ordinary PyTorch attention.
3. For the first acceptance run, also disable approximate denoising/conditioning experiments and the optional FP16 accumulation/intermediates/VAE flags. This isolates the baseline from known image-changing options. Retain quality-neutral local model/output caches and ordinary image transport.
4. Keep the user's optional settings available for later opt-in. A saved phone acceleration switch must not override notebook compatibility mode or make health claim an inactive feature is active. Clearly report skipped acceleration.
5. Reuse the two successful workers' actual compatible ComfyUI/package environment where available; capture it before changing a functioning instance. Otherwise select one fixed revision after reading the required node/bridge interfaces and validate it in the one-worker smoke. Do not invent a “known-good” revision or disturb working instances simply to test a new dependency stack.
6. Replace moving clone/pull behavior with a pinned, ownership-aware checkout. Preserve an unknown/modified existing checkout and explain the conflict.
7. Inspect dependency resolution before installation. Constrain the currently compatible Torch/torchvision/torchaudio family and CUDA wheel identity; install only required remaining dependencies. If the pinned ComfyUI revision cannot use them, fail with the concrete conflict. Do not blindly use `--no-deps` while ignoring missing dependencies, and do not quietly replace the GPU stack.
8. Add finite timeouts to network/install operations and enough stage output to distinguish slow progress from failure. This is not a mandate to write a new package manager.
9. Existing persistent custom nodes can import their own extensions. Inventory names/provenance and actual failing import logs. Bypass or repair only a proven problematic optional node, preserving user files; do not erase the custom-node directory.
10. Keep warm-up stage reporting and the existing decode-output check. First model copy/load/warm-up is startup cost. Do not label it steady-state generation speed.

The final working default may retain compatibility mode. Re-enabling experiments is not a release requirement. Do not spend GPU time benchmarking them once the normal workflow passes.

**Gate:** no optional native compiler/install route runs in compatibility mode; one worker reports ordinary attention and completes warm-up with the existing image checkpoint.

### Phase 3.5 — Diagnose the intermittent third-worker failure

Do not assume it is the same problem as the assistant failure. First distinguish **notebook setup**, **warm-up**, **tunnel connection**, **router readiness/catalog**, **render dispatch**, and **image retrieval**. The user has not identified which stage failed, so the plan must preserve that uncertainty.

Create one private, redacted three-row comparison at the failure stage: logical worker ID, runtime instance ID, notebook and actual loaded bridge fingerprints, ComfyUI revision, Python/Torch/CUDA/driver, GPU/host memory, distinct-versus-shared Drive identity, storage capacity, required checkpoint availability, optional-feature state, local health, router-reachable health, and current stage/error code. Compare credential matching as a Boolean; never include credential values.

- Confirm three worker entries identify the intended distinct processes/endpoints. A changed tunnel URL or saved credential may explain a connection problem; do not swap identities until the mismatch is demonstrated.
- Verify authenticated instance IDs are distinct. Unique configuration labels alone do not prove three actual workers. Independent VMs may legitimately use the same localhost ports and `/content` paths; those are not shared-state collisions.
- Compare the final same-version notebook across all three. Old open notebook cells/variables and moving ComfyUI revisions can produce different behavior.
- Reuse successfully warmed workers. Retry only the failed stage on the failed instance after recording its error.
- If instances share the same Drive account/folders, inspect concurrent writes to credentials, checkpoint partial files, auxiliary downloads, custom-node checkouts, inputs, and outputs. If their Drive accounts are separate, do not claim a shared-file race. Serialize only first-time shared artifact preparation or use bounded unique staging/promotion where the actual writer needs repair; do not design distributed storage.
- In shared storage, the current fixed `.part` checkpoint names, PID-only auxiliary temporary names, shared credential file, and directly written bridge module are concrete race risks. PID alone is not unique across VMs. Prefer reusing already-verified assets and one matched bootstrap; change only an implicated writer.
- Check the same-stage local endpoint before the tunnel endpoint. Local success plus remote failure points to addressing/authentication/tunnel limits rather than CUDA.
- Test A16 cheaply with two fast worker probes, one delayed/failing third probe, and a successful LLM probe. The health result must retain the successful observations and isolate the third failure.
- Fix A18 and test an explicit refresh after adding a checkpoint in a tiny catalog fixture: the new entry appears immediately, while routine cached probes remain cached. For live diagnosis, compare authenticated local health, router-reachable health, and an uncached catalog in up to three cheap sweeps spaced beyond the ten-second router cache; no renders are needed for these sweeps.
- When a tunnel URL/credential changes, update only the affected configured entry. An already-running router does not reread a Secret automatically. Restart its serving process when idle through its supported recovery path while reusing the LLM; this is different from restarting all notebooks.
- For rendering, preserve targeted retry and uncertain-acceptance rules. Never resubmit successful workers because the third failed.

**Gate:** the observed failure is identified or explicitly remains unreproduced; applicable confirmed defects have focused tests. The full live gate includes one isolated third-worker service restart/rejoin while the first two remain healthy. A single successful run cannot establish that all intermittent failures are eliminated.

### Phase 4 — Keep optional editing components optional

- Set `AUTO_SEGMENTATION=False` for the first working baseline, avoiding optional setup and host-memory use while diagnosing assistant failures. Preserve the guarded CPU SAM2 route and its disabled CUDA extension as an explicit option. Manual selection remains the resource-light fallback with a functioning LLM.
- Do not lower the SAM memory guard just to force installation. Setup success is not proof that mask inference fits; check available memory at actual use if the smaller model still leaves a reproducible failure.
- Test one automatic selection only if memory and current setup allow it. If it fails, make sure the existing correction request appears and the manual-mask path works. Do not add a new segmentation engine.
- Retain `FOOOCUS_DRIVE_RESERVE_GB=0.5` separately from the runtime-local 8-GiB reserve. Reuse existing verified auxiliary weights; a skipped auxiliary must expose the stock edit method honestly.
- With a working LLM, verify one manual-mask edit and exact preservation outside the normalized mask. An LLM box is not a semantic mask.
- If the LLM is unavailable, new edits currently cannot plan, even with a manual mask. Preserve a clear failure; do not promise a fallback that does not exist. Generation can still use its original prompt and retain unreviewed candidates.

**Gate:** optional segmentation/auxiliary problems do not masquerade as CUDA model-loading errors; the supported manual/stock route is correctly described and validated.

### Phase 5 — Regenerate notebooks and update only the relevant documentation

1. Use `.work-router/build_router_notebook.py` as the router notebook producer. Update its visible intro/config/load/serve text as well as embedded sources.
2. The worker's `.work-router/build_worker_notebook.py` is an in-place integration script, not a complete producer for every acceleration setting. Update worker cell literals deliberately and verify all affected embedded helpers.
3. Preserve current router port selection **8080, 8082, 8083, 8084**, with 8081 reserved for the LLM. Ensure the chosen port reaches environment, health request, and tunnel consistently.
4. Preserve the fact that a closed probe socket does not reserve a port. A bind race should report the actual startup failure; do not kill unrelated owners or reload the LLM as a response.
5. Parse every code cell without executing it; verify unique IDs, no saved outputs, exact embedded sources/hashes, correct source inventory, and intended default flags.
6. Generate/check the router notebook twice in a temporary output path to catch unstable generation where practical. Do not run old mutation scripts just because their filenames say “final.”
7. Update `README.md`, `ROUTER_MODEL.md`, `RUNTIME_SETUP.md`, `ROUTER_GUIDE.md`, and `VERIFICATION.md` where current behavior changes. Make only targeted corrections to speed docs needed to explain compatibility mode.
8. Distinguish current setup from the historical 27B stage plan. Do not rewrite history or leave the old 30-minute/90-minute build instructions as the recommended recovery path.
9. State exactly which new notebook files to upload. Old open Colab copies can retain earlier cells and variables. Use the final cleared notebook or confirm its build fingerprint; do not paste a second bootstrap over unknown state.
10. Keep the app protocol unchanged. The app already accepts dynamic model/revision strings in health. Rebuild Android only if app code, resources, dependencies, or its API contract actually changes.

**Gate:** the delivered notebook is self-contained and matches current source; documentation describes its actual defaults and supported deployment.

### Phase 6 — Run local checks before spending GPU time

Run the focused new setup/default tests first, then the existing router suite:

```powershell
# Run from E:\small_phonecollabaiproj using the existing test environment.
& '.\.work-router\test-venv\Scripts\python.exe' -m pytest tests/router -q -p no:cacheprovider
```

Do not upgrade the environment just to run this command. On another machine, use a suitable isolated environment and the repository's test requirements after checking availability/compatibility.

Minimum new meaningful coverage:

| Area | Cases to prove |
|---|---|
| Prebuilt installation | First probe fails then retry succeeds; corrupt archive/library rejected; confined extraction; unknown directory preserved. |
| No-compile policy | Incompatible router prebuilt never calls source build; worker compatibility mode never installs Sage/T4 attention or invokes compile on T4 and newer-GPU branches. |
| Identity / reuse | Same profile reuses before VRAM gate; model/projector/settings mismatch is rejected; fresh/reused provenance agrees. |
| Process handling | Startup interruption/timeout leaves no process owned by that attempt; unrelated port owner untouched; invalid CLI does not trigger a pointless CPU retry. |
| Diagnostics | Missing library, no GPU, bad hash, driver/probe failure, and timeout retain distinguishable reasons without secrets. |
| Adapter | Actual image payloads retained; invalid JSON/candidate IDs/scores rejected; overflow/failure does not invent a winner or silently lose input. |
| Real server contract | Wrong old schema wrapper rejected by the mock; enhancement/planning/review use the nested wrapper recognized by the pinned parser. |
| Partial health | Two successful workers and successful LLM result survive a delayed third-worker probe; stale results are identified. |
| Explicit refresh | Fresh phone catalog request bypasses the worker's cached list; ordinary preflight retains caching. |
| Existing behavior | Authentication, cancellation, serial deadline, uncertain worker acceptance, prepared-edit recovery, and zero-mask preservation remain covered. |

Use small fake archives, mocked processes/HTTP, and tiny image fixtures. A Linux process/child fixture is useful if process-group cleanup changes; do not compile CUDA to test timeout logic. Platform-dependent checks must say skipped/pending on Windows.

Update source checks that intentionally required old experimental defaults ON. The new checks must prove the intended compatibility policy, not merely change counts until a report passes.

Do not call `.work-router/verify_stage.py` a fresh end-to-end test: it reads saved XML and a prior worker summary, and hard-codes an old date. Adjust the small reporting path or write a fresh scoped report with command, timestamp, exit code, source hashes, and test scope. Reuse unchanged historical Android evidence with its real date.

**Gate:** relevant local checks pass on the final source. No stale evidence is relabeled as a fresh build or GPU result.

### Phase 7 — Small real-runtime acceptance

Perform this only with an available permitted runtime and existing authorized credentials. If that environment is unavailable, deliver the completed local repair and label this phase pending. Do not call the whole application runtime-verified.

**A. Assistant alone**

1. Capture the redacted environment snapshot and confirm there is no overlapping old compiler/server job.
2. Validate the prebuilt identity and CUDA device listing before downloading weights.
3. Download only the primary pair and verify exact bytes/SHA256. Record download time separately from loading time.
4. Start the assistant once. Record actual GPU layer/projector placement, available host RAM, process RSS, and device memory after load.
5. Check authenticated health/vision and then perform real structured text and image calls **through the same adapter used by the application**, with the corrected schema. Correlate HTTP/validation evidence with host/GPU memory. Stop at the first unexplained failure; health alone is insufficient.
6. Rerun the setup once; confirm the same matching process is reused with no download, build, or reload.

**B. Twelve small assistant cases, in a fail-fast order**

Use existing or simple local fixtures; do not generate twelve new SDXL images. Keep a short expected-result sheet before looking at responses.

Run one short exact-schema text case, then one tiny image case, then the full four-image case. These are part of the 12 cases. Stop at the first failure and fix/classify it before proceeding; do not spend twelve call deadlines reproducing a universal defect.

| Cases | Coverage / pass condition |
|---|---|
| Enhancement 1–4 | Explicit count; spatial relationship; named subject/style and exclusions; long input. Preserve essential constraints and negatives. A deliberately oversized input must fail explicitly without silent truncation. |
| Edit plan 1–4 | Local refinement, local replacement, whole-image change, directional outpaint. Use the actual source; allowed operation, strength and normalized coordinates; user intent retained. |
| Review 1–4 | Obvious count mismatch; obvious relationship mismatch; edit preservation using source plus three candidates; same candidate set reordered. Complete valid candidate IDs/scores, correct obvious winner, image-dependent explanation, no order-based change on an unambiguous case. |

All ordinary cases must produce valid complete structured output and meet the obvious semantic expectations. An intentional overflow case passes by producing the correct explicit failure. Borderline artistic taste is not a reason to launch a model search.

Record each call's elapsed time and observed memory, including the four-image case. Calls must finish within the existing 180-second deadline and the job deadline. Use modest periodic device/process sampling; label it **observed peak**, not an exact allocator peak.

Practical target: keep at least about **2 GiB VRAM headroom** on the target T4 during these cases and avoid host-memory exhaustion/swap thrashing. This is a target to measure, not a guaranteed property or fabricated minimum. A transiently lower margin requires a small repeat/diagnosis of that case; persistent tight fit fails the “realistic” goal. Do not add CPU offload silently to make the memory number look acceptable.

If 4B meets these checks, keep it. If it is stable but fails essential quality checks after one bounded prompt/template repair, unload it and evaluate the 9B pair with the same cases. If both fail, report the unmet requirement; do not silently disable essential assistant behavior and call the repair complete.

**C. One worker and the phone**

1. Start/reuse the historically unreliable worker first, if identifiable, in compatibility mode with the existing image checkpoint. Leave successful workers alone. Wait for a decoded warm-up output and authenticated health.
2. Configure a one-worker test using existing support for one to three entries; preserve the user's three-worker configuration for the final check. Do not overwrite Secret values in a shared artifact.
3. Submit one Balanced generation through the phone: verify original/effective prompt, returned image, saved settings, and storage after reopening.
4. Submit one manual-mask edit through the phone using the same checkpoint. Confirm it returns, records the edit method/lineage, and preserves unselected normalized-source pixels.
5. Check unavailable assistant/optional-feature labels using mocks or a controlled brief service stop after jobs finish; avoid deliberately breaking a long render.

**D. Existing three-worker configuration**

1. Add the other two existing workers only after the one-worker path passes.
2. Submit one generation and verify three accepted worker results, all retained candidates, actual image-based ranking, and the selected candidate's explanation.
3. Use that accepted job to check phone background/reconnect behavior. Confirm it resumes the same job ID and does not issue duplicate accepted renders.
4. If the third worker fails, preserve the two completed outputs and all accepted IDs. Diagnose that worker's exact stage and retry only a confirmed failure through the existing targeted retry path. Never repeat successful or uncertain accepted work. Review must cover only actual available candidates and must not invent a third result. A cheap fault-injection test covers this branch when the live job succeeds.
5. When idle, restart/rejoin only the previously problematic third worker once, with the final same-version notebook/configuration. Keep the healthy two and the LLM running. Confirm its new runtime ID/readiness without stale credentials or global restart. If its endpoint changes, restart only the router serving process after updating the affected entry. Use its existing warm-up or one small targeted request if needed; do not rerun the entire three-worker suite.
6. Do not repeat full three-worker editing if the one-worker edit and four-image assistant test already passed, unless a new integration failure justifies it.

**Gate:** baseline generation and manual editing work from the phone, multi-worker retention/review works when that deployment is available, and reconnect does not duplicate work. Automatic masking or Fooocus may remain explicitly degraded. Missing three-worker access must be labeled pending/limited rather than extrapolated from a single worker.

### Phase 8 — Deliver and stop

- Produce the updated active notebooks, changed source/tests, concise startup instructions, a change list, rollback instructions, and fresh scoped evidence.
- If packaging a finished deliverable, create a new dated bundle; never replace a frozen prior bundle. Include source/notebook hashes and matching reports.
- Include an APK only when actually rebuilt or clearly identified as the unchanged previously verified artifact. Do not imply a backend-only edit required a new APK.
- List each important feature as **passed live**, **passed locally**, **degraded with working fallback**, **blocked**, or **not tested**.
- Stop after the working baseline. Put optional speed/quality ideas in a short deferred list without implementing them.

## 7. Failure decisions

| Symptom | First decision | Do not do |
|---|---|---|
| Router begins compiling during ordinary setup | Stop this attempt's owned build, inspect stale notebook/defaults, load the final artifact. | Increase build timeout or run a second compiler. |
| Prebuilt cannot load shared libraries / glibc mismatch | Save exact loader error; confirm runtime facts; consider one verified compatible official binary. | Replace system libraries or assume smaller weights fix it. |
| GPU not visible / driver incompatible | Check actual driver/device visibility and binary pairing. | Reinstall Torch randomly; this server has private native libraries. |
| Wrong GGUF/projector/template | Compare exact profile, checksums, architecture, and command. | Pair a small model with the 27B projector or download another model blindly. |
| New model OOM | Check actual placement, duplicate processes, context/image case, and remaining memory. Make one justified change. | Disable integrity checks, repeatedly retry, or hide offload. |
| CPU RAM insufficient for SAM | Keep automatic selection unavailable and use a manual mask with working LLM. | Lower the memory guard or rebuild SAM's CUDA extension. |
| Fooocus lacks Drive space | Keep stock edit fallback and preserve existing weights. | Treat local-disk free space as Drive quota or delete models automatically. |
| Port occupied | Distinguish router port from LLM port; reuse authenticated owned session or use existing router choices. | Kill an unrelated process or reload weights to fix router binding. |
| Worker optional extension mismatch | Skip it in compatibility mode and use PyTorch attention. | Repair the extension before attempting a basic render. |
| Assistant invalid/slow response | Inspect actual bounded response/template and task case; keep truthful fallback. | Invent a selected candidate or treat JSON validity as visual correctness. |
| All LLM features fail despite ready status | First verify nested schema serialization and run the exact adapter smoke; collect error category and host/GPU memory. | Conclude that readiness proves inference works or that RAM is the only possible cause. |
| Two workers succeed, third fails | Compare instance/version/stage; test local health separately from tunnel/router health; retry only the failed stage. | Restart all four notebooks or reshuffle credentials until something happens to work. |
| Download interruption | Reuse verified complete files; retry once if the cause changed. | Re-download all models or add a complex resumable-download system incidentally. |
| No current GPU/phone access | Finish source, notebook, CPU tests and handoff; mark live checks pending. | Claim runtime success from mocks or stale reports. |

## 8. Deployment realism

The current design can configure one to three workers; three workers plus a separate assistant runtime are a larger deployment than a single notebook. Establish the smallest functioning setup first, then validate the user's existing full configuration.

Free managed Colab is not a dependable promise for this multi-runtime service: resources vary, and its FAQ restricts distributed workers on free managed runtimes and discusses termination of remote content-generation interfaces. Use a permitted runtime already available to the user. This plan does not provision paid capacity or treat a paid plan as automatically resolving every restriction. [Colab FAQ](https://research.google.com/colaboratory/faq.html).

Tunnel capacity is independent of model fit. The checked ngrok Free documentation lists three concurrent agents/endpoints and one assigned development domain; verify actual account capacity before promising four independent tunnels. Existing reachable private workers can avoid extra public tunnels only where the application's supported HTTPS/loopback addressing permits them. Do not weaken address validation to make an arbitrary LAN HTTP URL work. [ngrok Free limits](https://ngrok.com/docs/pricing-limits/free-plan-limits).

Do not assume `MOUNT_DRIVE=False` alone converts both notebooks into a portable local deployment. The worker currently imports Colab utilities and mounts Drive directly. If the available environment requires a local runtime, make only the explicit path/credential/mount changes required for that environment and validate them; otherwise record the deployment limitation. Do not turn this repair into a hosting migration.

## 9. Completion checklist

### Required for a locally complete repair

- [ ] Primary small-model pair and hashes are selected consistently.
- [ ] The adapter uses the pinned server's actual nested schema contract.
- [ ] Failed inference remains visible and produces a useful safe error category.
- [ ] A slow third worker cannot discard completed worker/LLM health results.
- [ ] Explicit catalog refresh reaches an uncached worker inventory.
- [ ] Default setup never invokes optional CUDA/native builds.
- [ ] Prebuilt failure/retry, bounded diagnostics, and owned startup cleanup work.
- [ ] Session reuse cannot accept the previous model or changed settings as the new profile.
- [ ] Worker source/dependency policy is reproducible and preserves its compatible GPU stack.
- [ ] Protocol, image settings, data, authentication, and accepted-job recovery remain intact.
- [ ] Notebook cells, embedded source, hashes, and visible defaults agree.
- [ ] Relevant existing and new local tests pass with fresh evidence.
- [ ] Documentation and rollback match the delivered files.

### Required before saying the current application works end to end

- [ ] The new assistant runs on the target runtime with acceptable measured memory headroom.
- [ ] Host-memory behavior is measured separately from GPU memory; the user's RAM suspicion is confirmed, rejected for the tested case, or explicitly unresolved.
- [ ] Actual text, edit-plan, and full four-image review calls pass the small acceptance set.
- [ ] Rerun reuses the correct process without rebuild/download/reload.
- [ ] The phone completes a generation and a manual-mask edit through one worker.
- [ ] The configured three-worker deployment retains/reviews all candidates, or its exact limitation is reported.
- [ ] The previously problematic third worker can restart/rejoin without resetting the healthy two; any unreproduced intermittent failure remains disclosed.
- [ ] Partial failure preserves successful outputs and accepted IDs; recovery targets only the confirmed failed worker.
- [ ] Reconnect follows the accepted job without duplicate generation.
- [ ] Optional-feature failures are visibly degraded and do not contradict completion claims.

“Local repair complete; live acceptance pending” is an accurate partial delivery when live access is missing. It is not equivalent to “everything works.”

## 10. Rollback

Rollback is scoped to files/configuration changed by this repair:

1. Stop only owned idle processes started with the new profile.
2. Restore changed source/notebooks from the Phase 0 backup and verify its manifest.
3. Restore the corresponding prior runtime profile/worker settings together; do not mix old embedded sources with new defaults.
4. Preserve job journal, source assets, prepared edits, credentials, model caches, and frozen bundles.
5. Reconnect using the actual router URL if its tunnel changed.
6. Verify health/provenance after restart. The old 27B profile remains a historical fallback with its original resource demands, not the recommended final state.

Before rollback with accepted work, wait for or deliberately cancel that work using the existing mechanism; do not reset persistent state to clear an error.

## 11. Handoff instruction for the execution chat

Copy this into the chat configured for **GPT-6.1 Sol / Ultra**:

> Execute E:\small_phonecollabaiproj\CURRENT_VERSION_RECOVERY_PLAN.md. The actual failures are that notebooks/app start but LLM-dependent actions fail, and one of three workers often needs retrying. Fix the confirmed LLM schema-contract defect, diagnose host RAM separately from VRAM/protocol issues, and use the pinned smaller 4B vision assistant. Make normal startup avoid optional CUDA compilation. Preserve the existing app/protocol, image checkpoint/settings, saved data, security, and recovery. Validate actual inference through the app's adapter and isolated third-worker recovery; readiness alone is not success. Treat the audit as a baseline to verify against current files. Use the single 9B fallback only for demonstrated essential quality failure. Do not run a broad model search, source-build marathon, UI redesign, or optimization project. Make only incidental improvements needed for the repair. Complete available local work and focused checks autonomously, then the bounded live acceptance if an authorized runtime is available. If blocked externally, deliver completed work and the exact remaining action with honest test scope. Stop once the working baseline passes.

## 12. Audit closure

This plan deliberately does not guarantee model quality, a ten-minute cold startup, a particular tokens-per-second rate, or unlimited free-runtime availability. Its model recommendation is based on verified artifact identity and architectural compatibility evidence, with acceptance gates for actual behavior.

Three independent reviews covered runtime lifecycle/prebuilt setup, model/contracts, and worker/notebook integration. The final plan is also checked against the user's resource constraint: each required change either enables the selected baseline, prevents a demonstrated setup failure, preserves an existing contract, or validates the claimed result. Broader improvements are deferred.
