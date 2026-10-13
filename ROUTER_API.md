# Router v2 contract (implementation reference)

JSON field names are camelCase. Existing worker ComfyUI endpoints remain unchanged. New app work uses one authenticated router; old direct-worker records retain their original transport.

`POST /phone-studio/v2/jobs`:

```json
{
  "schemaVersion": 2,
  "clientId": "stable-client-id",
  "requestId": "uuid",
  "operation": "generate",
  "originalPrompt": "user text",
  "negativePrompt": "negative tags",
  "parameters": {
    "model": "waiIllustriousSDXL_v170.safetensors",
    "lora": "", "loraStrength": 0.8,
    "width": 768, "height": 1024, "preset": "balanced",
    "baseSeed": 1001, "varySeedPerWorker": true, "speedExtras": true
  },
  "options": {"enhancePrompt": true, "reviewCandidates": true, "auxiliaryInpaint": true},
  "sourceAssetId": null, "maskAssetId": null,
  "editInstruction": null, "preservation": 0.65
}
```

Generate requires a nonempty originalPrompt; edit requires sourceAssetId and editInstruction. Presets are balanced/fast, resolving to 24/18 steps, CFG6.5, dpmpp_2m/karras. The optional `auxiliaryInpaint` option defaults true and enables stronger inpainting only when the worker and selected checkpoint support it; false selects the ordinary same-checkpoint edit graph. Client/server must reject invalid IDs, enum/numeric bounds and oversized fields. Assets are bounded multipart `file` uploads with optional `kind=image|mask`; upload replies have assetId, width, height, sha256. Uploads accept still PNG/JPEG/WebP, normalized to authenticated binary PNG, at most 24 MiB and 16 megapixels; no JSON base64.

Submission/recovery/status return the **full job snapshot** directly, not a nested job field. A missing request mapping returns 404; payload conflict returns 409. Each snapshot has:

```text
schemaVersion=2, studioId, jobId, clientId, requestId, revision,
operation, state, createdAtMillis, updatedAtMillis, deadlineMillis,
originalPrompt, effectivePrompt, negativePrompt, parameters, options,
sourceAssetId?, maskAssetId?, editInstruction?, editPlan?, preparedEdit?,
enhancementStatus, warnings[], error?,
workers[], candidates[], selection
```

Workers: workerId, name, seed, state, stage, stepsDone, stepsTotal, runtimeId, promptId, error. Internal renderMetadata records the reserved parameters, actual positive/negative prompts and effective acceleration/inpaint flags before submission; recovery follows the accepted recipe even if worker capability reporting changes. States include pending/submitting/queued/rendering/complete/failed/skipped/cancelled/submission_uncertain. Parent states: accepted/enhancing/planning/dispatching/rendering/collecting/reviewing/complete/partial/failed/cancelled/submission_uncertain. Parent complete/partial means candidate storage/review has finished, not merely sampling.

Candidates: candidateId, assetId, workerId, workerName, seed, width, height, model, lora, loraStrength, steps, cfg, sampler, scheduler, speedExtras, originalPrompt, effectivePrompt, negativePrompt, sourceAssetId, editInstruction. Additive edit metadata includes editMode, fooocusInpaint, workingWidth/workingHeight and editPreparation (crop, source/output sizes, strength, normalization, selection method/revision and outpaint margins). Metadata records actual effective settings.

`preparedEdit` is an internal versioned manifest with `assets` mapping sourcePath/maskPath/originalPath/finalMaskPath/selectionMaskPath to opaque durable asset IDs and `metadata` containing only the non-path preparation fields. All actual crop/source/selection/feathered-mask files are durably saved before a worker reservation. Recovery uses this exact manifest and does not rerun SAM or reconstruct an accepted edit from a potentially changed mask. No local paths or worker credentials appear in the public manifest.

Retry accepts optional `{ "requestId": "unique-retry-key" }`, keeps the parent jobId/requestId, and retries only confirmed failed/skipped/cancelled workers. Repeating a saved retry key returns the current full snapshot without retrying again. `submission_uncertain` workers block retry; an unkeyed retry while active returns 409.

Selection: status=pending|selected|disabled|unavailable, winnerCandidateId?, reason, scores[], reviewerModel, reviewerRevision. Score objects: candidateId, adherence, preservation, quality (0–10), reason. A selected winner must name an existing candidate. Disabled/unavailable selection has no invented winner; app exposes all candidates with the appropriate label.

Socket frames are `{ "type": "job", "jobId": "…", "revision": 3 }`; they wake an authoritative GET. Server sends the current revision on subscription and whenever it changes. Upload/status/download/model calls use the same Basic/Studio-token auth. Do not send worker credentials in any response.

Router health: ok, service="phone-studio-router", instanceId, studioId, protocolVersion=2, capabilities={generation,editing,visionReview,promptEnhancement}, llm={ready,model,revision,degraded,message}, workers=[{workerId,name,online,checkpointCount,message}]. Catalog keeps existing checkpoints/loras/defaultCheckpoint fields and adds availability maps keyed by filename to workerId lists. Legacy health/catalog clients can ignore additive fields.

Router model downloads also retain `/phone-studio/download-model` and `/phone-studio/downloads/{id}` as compatibility routes; new requests may supply workerId or `all`. Aggregate status keeps jobId/status/progress/filename/error and adds worker statuses. Router builds all graphs, never accepts an app-provided arbitrary graph.

## Python module integration

`router.llm.LLMClient(base_url, api_key='', model_id=..., revision=...)`:

- `async health() -> dict` (ready/model/revision/degraded/message).
- `async enhance(request: dict) -> dict` (effectivePrompt/status/warnings).
- `async plan_edit(request: dict, source_path: Path) -> dict` (mode=global|refine|replace|outpaint, positivePrompt, negativePrompt, denoise, targetText, boxes/points normalized to 0–1, preservedFeatures, warnings).
- `async review(request: dict, candidates: list[dict], asset_paths: dict[str, Path]) -> dict` (selection schema; optional source path passed through asset_paths under sourceAssetId).
- `async close()`.

`router.workflows`:

- `build_generation(parameters: dict, positive: str, negative: str, seed: int) -> dict`.
- `build_edit(parameters: dict, positive: str, negative: str, seed: int, source_name: str, mask_name: str|None, mode: str, denoise: float, fooocus: bool=False) -> dict`.

`router.editing`:

- `prepare_edit(source_path: Path, mask_path: Path|None, plan: dict, work_dir: Path) -> dict`, blocking CPU work, called in a worker thread. Returns sourcePath/maskPath/originalPath, box=[x,y,w,h], originalSize=[w,h], width/height, mode/denoise, warnings, and explicit degradedMask flag if needed. Automatic selection must never silently pretend an approximate rectangle is a semantic mask.
- `finish_edit(prepared: dict, candidate_path: Path, output_path: Path) -> Path`, blocking CPU compositing, called in a worker thread. Preserve unselected normalized source pixels and do not overwrite source.

Segmentation uses `PHONE_STUDIO_SAM2_CHECKPOINT` and `PHONE_STUDIO_SAM2_CONFIG` when installed, CPU by default. Failure requires visible correction/manual mask for local edits. Fooocus use is worker-capability-checked and recorded; ordinary graph fallback is labeled. Editing disables incompatible speed hooks rather than claiming unverified patch combinations are accelerated.
