# Router-stage setup and usage

For current startup, use [RECOVERY_STARTUP.md](RECOVERY_STARTUP.md), beginning with one worker and real adapter inference. The refreshed 0.3 app scans a private router QR or imports its paste code; see [APP_REFRESH.md](APP_REFRESH.md).

This stage was planned before implementation in [ROUTER_STAGE_PLAN.md](ROUTER_STAGE_PLAN.md). The attached research report informed model choice; instructions in that document were not adopted as user instructions.

## Four independent runtimes

Use three instances of `PHONE_STUDIO_COLAB.ipynb` and one instance of `PHONE_STUDIO_ROUTER_COLAB.ipynb`. Distinct accounts are represented by independent Secrets/tunnels; the code does not manage accounts. T4/16 GB is the intended worker baseline and the initial router target with a provisional 4B budget; actual fit/inference remain unverified. Free managed Colab does not promise this deployment; permitted/local runtimes can use the same roles.

Each image worker retains the existing Secrets: `NGROK_AUTHTOKEN`, optional assigned `NGROK_DOMAIN`, `PHONE_STUDIO_TOKEN`, `TUNNEL_PASSWORD`, and optional `CIVITAI_API_KEY`. Keep the worker's printed connection record privately. Each worker must have the desired checkpoint and LoRA. Missing files are reported as unavailable workers rather than silently substituted models.

On the router, configure these Secrets and grant notebook access:

| Secret | Purpose |
| --- | --- |
| `NGROK_AUTHTOKEN` | Router's own tunnel account token |
| `NGROK_DOMAIN` | Optional router domain assigned to that ngrok account |
| `TUNNEL_USER` | Router Basic-auth username; defaults to studio |
| `TUNNEL_PASSWORD` | Existing router Basic-auth password; optional, generated/persisted privately when missing |
| `PHONE_STUDIO_TOKEN` | Existing router API token; optional, generated/persisted privately when missing |
| `PHONE_STUDIO_WORKER_CODES` | Easier setup: private worker codes, one per line, complete list of one to three stable worker IDs |
| `PHONE_STUDIO_WORKERS_JSON` | Existing private worker records, used when the code Secret is empty |

Worker JSON example (replace placeholders; never share real values):

```json
[
  {"workerId":"worker-1","name":"Worker 1","serverUrl":"https://worker-one.example","tunnelUser":"studio","tunnelPassword":"placeholder","studioToken":"placeholder"},
  {"workerId":"worker-2","name":"Worker 2","serverUrl":"https://worker-two.example","tunnelUser":"studio","tunnelPassword":"placeholder","studioToken":"placeholder"},
  {"workerId":"worker-3","name":"Worker 3","serverUrl":"https://worker-three.example","tunnelUser":"studio","tunnelPassword":"placeholder","studioToken":"placeholder"}
]
```

Use final HTTPS addresses without embedded credentials/query/fragment. Domains cannot be shared by simultaneous independent servers. Tunnel/account capacities still apply. When a worker URL changes, wait until idle and interrupt the router serving cell, update only that entry in its Secret, rerun the router configuration cell, then rerun serving against the same persistent state folder. Leave model and smoke cells untouched; accepted worker submissions are recovered without blindly resending them.

Run the updated router cells in order. It validates the pinned official b11146 prebuilt before downloading the 4B pair (3.148 GiB); normal startup does not compile CUDA or replace Torch/CUDA. The functional smoke cell calls the real application's adapter with text and image fixtures and saves private memory/timing/output evidence. Inspect semantic expectations before continuing. Automatic CPU-projector retry and SAM setup are off for the baseline. The serving cell chooses 8080, 8082, 8083 or 8084; 8081 remains private.

Default persistent state remains `MyDrive/PhoneStudioRouter`. The primary cache is runtime-local `/content/phone_studio_llm_models/4b-4a5daa6fbefca5fe822dc65fcb95cc4576fa9720/`. Keep the same state folder for studio identity, jobs and candidate assets. Only one active router may use it. Preserve old caches and credentials. A matching owned LLM session reuses before the fresh-memory gate; different profile/settings/integrity is a conflict.

## Generate and compare

Describe what you want, choose the checkpoint, and use Balanced or Fast. **Improve my prompt** and **Choose the closest match** default on. The first converts the request to concise Danbooru-style tags; negatives stay unchanged. The second sees the actual rendered candidates and judges against the original request, not only the rewritten tags. Defaults and switches are saved.

The progress rail shows assistant stages and each worker's actual progress/error. A revision socket wakes an authoritative status read; bounded polling works if the socket disconnects. Sampling completion is followed by durable collection and review before the job is ready. All candidates remain stored. The selected image appears first; **Other versions** reveals the rest in Create/Library.

If prompt enhancement fails, the original prompt is used with a warning. If review fails or is disabled, no artificial winner is declared and all available versions are shown with the corresponding status. The information button exposes original/effective prompt, seed/settings, review status/reason and edit lineage.

## Edit

Choose an existing image's pencil icon, or **Edit image → Choose an image**. The picker copies an orientation-normalized, lossless PNG to app-private storage; it does not request broad photo access. A source must be at most 16 megapixels and its lossless copy at most 24 MiB. Large images may require a smaller source on memory-limited phones.

Write a concrete instruction such as “replace the mug with a blue vase; keep the hand and table.” The assistant examines the source and chooses an approved edit mode. Higher **Preserve the source** asks for a gentler edit. The selected SDXL checkpoint and LoRA remain the image model; global changes may alter identity/composition.

**Automatic area** is unavailable in the repaired baseline because automatic SAM setup is off; use **Paint area**. With explicit SAM opt-in it uses visual target coordinates plus SAM2.1 Tiny CPU segmentation when available. Low confidence or missing segmentation returns a clear error requesting manual correction. **Paint area** enables a brush/eraser and undo. Paint the area to change; an empty manual selection cannot be submitted. Returning to Automatic clears the painted selection. Mode, strokes, instructions and preservation choice are saved separately from the generation prompt.

For local edits, contextual crop/inference/stitching preserves zero-mask normalized source pixels exactly. Feathered boundary pixels can change. Orientation/color normalization can change decoded source representation before that guarantee. Outpainting preserves the placed source rectangle while creating new edges; clear any painted mask before requesting expansion. Whole-image changes have no outside-mask preservation promise. Automatic selection and generated detail remain unverified visually.

Fooocus auxiliary inpainting is requested on by default in the worker notebook, but only used with a supported WAI v170 replacement/outpaint recipe and verified node capability. The pinned patch/head add approximately 1.23 GiB to worker storage; the base checkpoint stays the same. Unsupported or unavailable patch setup uses an explicitly labeled ordinary edit graph. Explicitly enabled SAM setup uses approximately 149 MiB of pinned weights and CPU inference without replacing existing Torch/CUDA. Editing bypasses incompatible per-render speed hooks. Exact auxiliary identities/operations are retained in router metadata.

The phone's saved **Stronger inpainting** switch defaults on and controls whether an edit requests the auxiliary patch. Turn it off to compare the ordinary graph with the same checkpoint; the actual method is recorded per candidate. Advanced IPAdapter/ControlNet and uncommon `model_as_lora` combinations are outside this stage's supported auxiliary recipe.

Before reserving a worker, the router persists the prepared source crop, automatic/manual mask and blend mask. Recovering an accepted edit after a restart reuses these assets rather than repeating segmentation; retain the same persistent state folder.

## Recovery and errors

| Situation | Expected behavior / next step |
| --- | --- |
| Phone closes during a render | Foreground service continues where Android allows; relaunch follows the saved parent job. Drafts remain saved. |
| Router tunnel disconnects | Accepted job continues on router; phone reconnects using job/request IDs. Update the existing connection URL if needed. |
| Router VM restarts | Restart with the same persistent state folder and current worker URLs. Journal snapshots/assets restore accepted state. |
| Different router state folder | Phone reports changed studio identity; restore the original folder before recovering the request. |
| Worker times out or lacks checkpoint | Other candidates remain; **Retry just these** targets confirmed failures with recorded seeds. |
| A known accepted render cannot be followed/copied | Retry preserves its prompt/runtime/request IDs and only follows/downloads that result; a matching authenticated runtime is required. |
| Worker acceptance is uncertain | No automatic resubmission; inspect/recover the worker job before creating another render. |
| Automatic mask fails | Choose Paint area, mark the target and submit the corrected draft as a new edit. |
| Stop | Best-effort targeted cancellation; an accepted render can finish when its worker lacks safe targeted interruption. |
| LLM will not fit/start | Read setup's clear failure; no silent model downgrade. Same-weight CPU projector fallback, if used, is labeled. |
| Images disappear from old library tiles | Reconnect the matching persistent router folder; older unused assets can expire under the 2 GiB budget. |

Downloads from the phone are forwarded to all configured workers by default. Each worker still uses its own Civitai key and Drive storage. Partial download failures are reported; refresh the catalog to confirm actual availability before generating.

## Runtime verification and evidence

1. **Connection:** health identifies `phone-studio-router`, protocol 2, intended studio identity, pinned LLM revision and three worker statuses.
2. **Default review:** generate a prompt with a precise count/relationship; inspect the selected image and all alternatives and decide whether the choice follows the request.
3. **Switches:** disable prompt assistance/review separately; confirm original prompt and unreviewed alternatives remain accessible.
4. **Edit preservation:** paint a small area; compare source/output, especially untouched pixels, face and boundary. Check auxiliary/fallback metadata.
5. **Persistence:** close/reopen and rotate with an edit draft; confirm source, instructions, mask, generation settings and accepted job survive.
6. **Recovery:** briefly disconnect a tunnel and restore it; confirm one parent job and no duplicate worker prompt. Retry a confirmed failed worker and confirm successful candidates remain.
7. **Speed:** separate cold startup from warm renders; collect three distinct seeds and matching worker/`PhoneStudioTiming`/`[phone-studio-router-timing]` lines. Include GPU/runtime versions, flags, model placement/degraded status and any visual differences; omit credentials.

Worker GPU-sync stage instrumentation remains opt-in to avoid diagnostic synchronization in normal renders. Phone timing logs are enabled and bounded; router timing measures enhancement/planning/review and parent stages. These are available for later evaluation, not measured performance claims.
