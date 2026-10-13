# Current router assistant and setup

The default is **Huihui-Qwen3.5-4B-abliterated Q4_K_M with its matching f16 vision projector**, a third-party mradermacher quantization of Huihui's model based on Qwen3.5-4B. The pinned repositories declare Apache-2.0. Publisher claims about abliteration do not guarantee refusal behavior or retained accuracy. Workers still generate/edit pixels with the existing SDXL checkpoint; prompts, images, editing contracts and reviewer provenance remain preserved.

The authoritative identities and serving settings are `router/model_profile.py`. The router configuration, adapter and setup import them; the notebook embeds that module. Existing historical reviews retain their actual model identity.

## Exact primary artifacts

Repository: `mradermacher/Huihui-Qwen3.5-4B-abliterated-GGUF`.
Revision: `4a5daa6fbefca5fe822dc65fcb95cc4576fa9720`.

| Artifact | Bytes | SHA256 |
| --- | ---: | --- |
| Huihui-Qwen3.5-4B-abliterated.Q4_K_M.gguf | 2,707,514,688 | `423f10b6ec2d99c3378143d7cd3b80eb4887b3ed92103103ac59173b404f4f7c` |
| Huihui-Qwen3.5-4B-abliterated.mmproj-f16.gguf | 672,423,552 | `f14643c11f1e8244c59bca670e2a4c843be4234aa6bb88d0647dae7297798686` |

Total: **3,379,938,240 bytes / 3.148 GiB**. Exact publisher-hosted metadata was rechecked; weights were not downloaded in local verification. [Immutable metadata](https://huggingface.co/api/models/mradermacher/Huihui-Qwen3.5-4B-abliterated-GGUF/revision/4a5daa6fbefca5fe822dc65fcb95cc4576fa9720?blobs=true), [Huihui model card](https://huggingface.co/huihui-ai/Huihui-Qwen3.5-4B-abliterated).

Downloads use revision-specific URLs, exact sizes/SHA256s and atomic promotion. The default cache is `/content/phone_studio_llm_models/4b-4a5daa6fbefca5fe822dc65fcb95cc4576fa9720/`. The old model/projector remains untouched. Never mix projectors between profiles.

## Sole conditional quality fallback

Only after stable 4B loading/inference but indispensable quality failure after one targeted prompt correction: explicitly choose `model_profile='9b', quality_fallback_confirmed=True`. Unload the prior model first; download one pair at a time. This does not fix protocol, loader, driver, authentication or memory errors.

Repository: `mradermacher/Huihui-Qwen3.5-9B-abliterated-GGUF`.
Revision: `9f646d7eda193ddf2348134f3bff3d49eed7a2c6`.

| Artifact | Bytes | SHA256 |
| --- | ---: | --- |
| Huihui-Qwen3.5-9B-abliterated.Q4_K_M.gguf | 5,627,045,248 | `ea1858ef4dc4b648b8dbb44612962a0333e945060dd0545ac0f28d7c4416e4b3` |
| Huihui-Qwen3.5-9B-abliterated.mmproj-f16.gguf | 918,166,016 | `56f07ff42fc9ab24fc06a93dce5a48fb2dbe08bff1a1c6e519d50af450820148` |

Total: **6.096 GiB**. No fallback is downloaded or selected automatically. [Immutable metadata](https://huggingface.co/api/models/mradermacher/Huihui-Qwen3.5-9B-abliterated-GGUF/revision/9f646d7eda193ddf2348134f3bff3d49eed7a2c6?blobs=true).

## Serving policy and bounded setup

Normal startup uses official **llama.cpp b11146**, commit `7fe450e19305b828c199d602c23a8337aaa1f03b`, with separately pinned CUDA 12.8 Linux x86_64 server/runtime archives. Linux/glibc 2.38+, version identity and CUDA device probes precede weights. System libraries and Torch are not replaced. Source build stays disabled; its old explicit opt-in path is outside the validated baseline. [Official release](https://github.com/ggml-org/llama.cpp/releases/tag/b11146).

Archives are size/hash checked and confined on extraction. Staging is probed with its private libraries, stamped with regular-file/symlink/library integrity, then published atomically under a small exclusive lock. Failed probes remove only owned staging and preserve reusable archives. Unknown/unstamped/changed final directories are preserved with a confined quarantine instruction. Probe diagnostics exist in the stated private log, including stage, status and timeout.

Serving remains **8192 context, one serial slot, batch 256, microbatch 128, f16 KV, image maximum 1024 tokens, thinking disabled**, and the existing 1280-side analysis preview. All source/candidate images remain in the request; no silent truncation or lower SDXL settings are introduced. Automatic fitting remains visible in the server log. Automatic CPU-projector retry is off; any explicit retry is limited to demonstrated GPU allocation pressure with adequate separately measured host RAM.

The primary preflight estimate is artifact MiB plus 1 GiB compute, 1 GiB context/images and 2 GiB headroom (about 7319 MiB free). This is a **provisional estimate, not a measured memory minimum**. A T4/SM75 is the initial target; no expanded Windows/smaller-GPU baseline was validated. Keep the 8 GiB disk reserve; account for archives/extraction separately. Host RAM is independent of VRAM, and process RSS includes shared/file-backed mappings. RAM admission uses process-cgroup and accessible ancestor bounds; unknown bounds cannot authorize optional CPU retry.

Session fingerprints include exact pair/revision, server identity, serving settings, port and projector/degraded policy. Exported adapter URL/key/degraded fields must agree with the authenticated session before reuse. Ownership checks bind PID/start identity and server model alias; installed files are verified before reuse. A healthy matching session reuses before fresh free-VRAM admission. Profile/settings mismatch or occupied unrelated port stops with a conflict. Interrupted/failed startup cleans up only the process started by that attempt and preserves logs.

The LLM binds loopback on 8081 with a private generated API key. Only the authenticated router is tunneled on its selected port among 8080/8082/8083/8084. Native agent/web UI/MCP proxy stay disabled; child environments exclude router/worker Secrets. Tunnel account capacity remains independent of model fit and is not provisioned by this repair.

## Application adapter and acceptance

The pinned server reads `response_format.json_schema.schema`. The repaired adapter now uses that wrapper for enhancement, edit planning and actual image ranking; the previous sibling schema was a confirmed defect. [Pinned parser](https://github.com/ggml-org/llama.cpp/blob/7fe450e19305b828c199d602c23a8337aaa1f03b/tools/server/server-common.cpp#L1185-L1203).

Output remains validated: approved edit operations/regions, finite scores, exact candidate coverage, highest-adherence selection and no executable output. Invalid enhancement uses the original prompt with an unavailable label; invalid review retains all candidates without inventing a winner. New manual-mask edits still require a working planner. Calls retain the 180-second deadline including serial-slot waiting and cancellation.

Diagnostics distinguish transport/authentication, server rejection/context overflow, queue/inference deadlines, incomplete output, malformed JSON and invalid task fields. Logs contain bounded request/task IDs, image counts/dimensions, schema/profile fingerprints, HTTP status, allowlisted server type/code, finish/usage/reasoning metadata and durations. They exclude prompt/image/credential bodies and never forward arbitrary upstream messages to the phone. Host OOM and GPU OOM require separate memory/process/log evidence.

Health preserves existing fields and adds `processReady`, `inferenceStatus`, `lastInference` and useful degradation messages. Health polling does not run inference, and a successful process probe does not erase a failed task. The existing `ready` field becomes false after failed/unvalidated inference so the unchanged phone displays its safe message; `processReady` stays independently true. An initially untested reachable process retains initial readiness with `inferenceStatus=untested`. Slow worker/catalog checks no longer discard completed LLM/worker observations; expired observations are marked stale/unready. Explicit phone refresh sends uncached worker inventory.

Automatic SAM is off for the baseline, with its guarded CPU route preserved as explicit opt-in. Manual selection avoids optional segmentation setup; stock editing remains when Fooocus is unavailable, with its separate Drive reserve unchanged.

Follow [RECOVERY_STARTUP.md](RECOVERY_STARTUP.md): two actual adapter smokes, one source-plus-three review, the remaining small semantic cases, one-worker generation/manual edit, then multi-worker recovery. Read [RECOVERY_VERIFICATION.md](RECOVERY_VERIFICATION.md) for the current local scope. Model fit, host-memory cause, real quality/latency and phone/isolated third-worker operation were not established by CPU mocks or notebook parsing.
