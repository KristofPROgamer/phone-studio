"""Durable router orchestration. Phone jobs remain independent of tunnel lifetimes."""
from __future__ import annotations

import asyncio
import contextlib
import copy
import math
import shutil
import time
import uuid

from .assets import AssetStore
from .config import Config, RouterError, identifier, validate_request
from .journal import Journal, TERMINAL, now_ms
from .llm import LLMClient, LLMUnavailable
from .workers import WorkerClient, WorkerFailure
from .workflows import build_generation, build_edit
from .editing import prepare_edit, finish_edit, MaskCorrectionRequired

WORKER_TERMINAL = {"complete", "failed", "skipped", "cancelled", "submission_uncertain"}


class RouterService:
    def __init__(self, config: Config, *, journal=None, assets=None, workers=None, llm=None):
        self.config = config
        self.journal = journal or Journal(config.root, config.drive)
        self.assets = assets or AssetStore(config, self.journal)
        self.workers = workers or WorkerClient(config)
        self.llm = llm or LLMClient(config.llm_url, api_key=config.llm_api_key,
                                   model_id=config.llm_model, revision=config.llm_revision)
        self.instance_id = str(uuid.uuid4())
        self.tasks = {}
        self.listeners = {}
        self.job_slot = asyncio.Semaphore(1)
        self._submit_lock = asyncio.Lock()
        self._closing = False
        self._health_cache = None
        self._health_at = 0.0
        self._llm_health = {"ready": False, "model": config.llm_model, "revision": config.llm_revision,
                            "degraded": False, "message": "Prompt assistant readiness has not been confirmed."}

    async def start(self):
        await self.workers.start()
        for job in await asyncio.to_thread(self.journal.jobs):
            if job["state"] not in TERMINAL:
                self.schedule(job["jobId"])

    async def close(self):
        self._closing = True
        for task in self.tasks.values():
            task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        await self.workers.close()
        await self.llm.close()
        await asyncio.to_thread(self.journal.close)

    def schedule(self, job_id):
        if self._closing or (job_id in self.tasks and not self.tasks[job_id].done()):
            return
        task = asyncio.create_task(self._run_guarded(job_id), name=f"router-job-{job_id}")
        self.tasks[job_id] = task
        def completed(done):
            if self.tasks.get(job_id) is done:
                self.tasks.pop(job_id, None)
        task.add_done_callback(completed)

    async def get(self, job_id):
        return await asyncio.to_thread(self.journal.get, identifier(job_id, "Job ID"))

    async def update(self, job_id, transform, durable=True):
        job = await asyncio.to_thread(self.journal.update, job_id, transform, durable)
        for listener in self.listeners.get(job_id, set()):
            listener.set()
        return job

    async def set_fields(self, job_id, **fields):
        return await self.update(job_id, lambda job: job.update(fields))

    async def _store_prepared_edit(self, prepared):
        """Freeze actual masks/crops before any worker can accept their graph."""
        paths = ("sourcePath", "maskPath", "originalPath", "finalMaskPath", "selectionMaskPath")
        assets = {}
        for field in paths:
            if prepared.get(field):
                kind = "mask" if field in ("maskPath", "finalMaskPath", "selectionMaskPath") else "image"
                asset = await asyncio.to_thread(self.assets.ingest, prepared[field], kind)
                assets[field] = asset["assetId"]
        metadata = {key: copy.deepcopy(value) for key, value in prepared.items() if not key.endswith("Path")}
        return {"version": 1, "assets": assets, "metadata": metadata}

    async def _restore_prepared_edit(self, manifest, uploaded_source):
        if not isinstance(manifest, dict) or manifest.get("version") != 1 or not isinstance(manifest.get("assets"), dict) or not isinstance(manifest.get("metadata"), dict):
            raise RouterError("Saved edit preparation is invalid. Accepted worker renders will not be recreated.", 409, "edit_preparation_missing")
        prepared = copy.deepcopy(manifest["metadata"])
        for field in ("sourcePath", "maskPath", "originalPath", "finalMaskPath", "selectionMaskPath"):
            asset_id = manifest["assets"].get(field)
            prepared[field] = str(await asyncio.to_thread(self.assets.path, asset_id)) if asset_id else None
        if not prepared["sourcePath"] or not prepared["originalPath"]:
            raise RouterError("Saved edit source/crop is missing. Accepted worker renders will not be recreated.", 409, "edit_preparation_missing")
        prepared["uploadedSourcePath"] = str(uploaded_source)
        return prepared

    async def submit(self, body):
        request = validate_request(body)
        async with self._submit_lock:
            # Duplicate acceptance is valid even when the queue is full.
            try:
                existing = await asyncio.to_thread(self.journal.recover, request["clientId"], request["requestId"])
            except RouterError as error:
                if error.status != 404:
                    raise
                existing = None
            if existing is None:
                jobs = await asyncio.to_thread(self.journal.jobs)
                if sum(job["state"] not in TERMINAL for job in jobs) >= self.config.max_queued_jobs:
                    raise RouterError("The router queue is full. Wait for a render to finish.", 429, "queue_full")
                if request["sourceAssetId"]:
                    source = await asyncio.to_thread(self.journal.asset, request["sourceAssetId"])
                    if source["kind"] != "image":
                        raise RouterError("Choose an image asset as the edit source.")
                    if request["maskAssetId"]:
                        mask = await asyncio.to_thread(self.journal.asset, request["maskAssetId"])
                        if mask["kind"] != "mask" or (source["width"], source["height"]) != (mask["width"], mask["height"]):
                            raise RouterError("The edit mask must match the source image dimensions.")
            workers = []
            for index, worker in enumerate(self.config.workers):
                seed = request["parameters"]["baseSeed"]
                if request["parameters"]["varySeedPerWorker"]:
                    seed = (seed + index) & 9223372036854775807
                workers.append({"workerId": worker.worker_id, "name": worker.name, "seed": seed,
                    "state": "pending", "stage": "Waiting", "stepsDone": 0, "stepsTotal": 0,
                    "runtimeId": "", "promptId": None, "error": None,
                    "requestId": str(uuid.uuid4()), "clientId": f"router-{uuid.uuid4()}", "submissionAttempted": False})
            job, _ = await asyncio.to_thread(self.journal.create_job, request, workers, self.config.job_timeout_seconds)
            if job["state"] not in TERMINAL:
                self.schedule(job["jobId"])
            return job

    async def health(self):
        if self._health_cache is not None and time.monotonic() - self._health_at < 10:
            return copy.deepcopy(self._health_cache)
        worker_task = asyncio.create_task(self.workers.probes(timeout=3.5))
        llm_task = asyncio.create_task(self.llm.health())
        tasks = (worker_task, llm_task)
        try:
            done, _ = await asyncio.wait(tasks, timeout=4)
            if worker_task in done and not worker_task.cancelled() and worker_task.exception() is None:
                observed = worker_task.result()
            else:
                observed = []
                for worker in self.config.workers:
                    previous = self.workers.observed.get(worker.worker_id, {})
                    observed.append({**previous, "workerId": worker.worker_id, "name": worker.name,
                        "online": False, "checkpointCount": 0, "stale": bool(previous),
                        "probeStage": "aggregate_timeout", "message": "Worker readiness check did not complete; previous observation is stale."})
            if llm_task in done and not llm_task.cancelled() and llm_task.exception() is None:
                llm = {**llm_task.result(), "stale": False, "observedAtMillis": now_ms()}
                self._llm_health = llm
            else:
                llm = {**self._llm_health, "ready": False, "processReady": False, "stale": True,
                       "message": "Prompt assistant health check did not complete; previous observation is stale."}
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        safe_workers = [{key: item[key] for key in ("workerId", "name", "online", "checkpointCount", "message",
            "runtimeId", "probeStage", "stale", "observedAtMillis", "workerRuntime") if key in item} for item in observed]
        result = {"ok": True, "service": "phone-studio-router", "instanceId": self.instance_id,
                "studioId": self.journal.studio_id, "protocolVersion": 2,
                "capabilities": {"generation": True, "editing": True,
                                 "visionReview": bool(llm.get("ready")), "promptEnhancement": bool(llm.get("ready"))},
                "llm": llm, "workers": safe_workers}
        self._health_cache, self._health_at = result, time.monotonic()
        return copy.deepcopy(result)

    async def catalog(self, *, cached=False):
        observed = await self.workers.probes(cached=cached)
        checkpoints, loras = {}, {}
        for worker in observed:
            for name in worker["checkpoints"]:
                checkpoints.setdefault(name, []).append(worker["workerId"])
            for name in worker["loras"]:
                loras.setdefault(name, []).append(worker["workerId"])
        defaults = [item.get("defaultCheckpoint") for item in observed if item.get("defaultCheckpoint") in checkpoints]
        return {"checkpoints": sorted(checkpoints), "loras": sorted(loras),
                "defaultCheckpoint": defaults[0] if defaults else next(iter(sorted(checkpoints)), ""),
                "availability": {"checkpoints": checkpoints, "loras": loras}}

    async def _run_guarded(self, job_id):
        try:
            async with self.job_slot:
                job = await self.get(job_id)
                if job["state"] in TERMINAL:
                    return
                remaining = (job["deadlineMillis"] - now_ms()) / 1000
                if remaining <= 0:
                    raise RouterError("Router deadline expired. Accepted worker renders may still finish.")
                async with asyncio.timeout(remaining):
                    await self._run(job_id)
        except asyncio.CancelledError:
            # Process shutdown preserves the journal for reconciliation. Explicit
            # cancel has already persisted its terminal state before cancellation.
            raise
        except Exception as error:
            job = await self.get(job_id)
            if job["state"] == "cancelled":
                return
            if isinstance(error, (RouterError, WorkerFailure, MaskCorrectionRequired, LLMUnavailable)):
                message = str(error)
            elif isinstance(error, TimeoutError):
                message = "Router deadline expired. Accepted worker renders may still finish."
            else:
                message = "Router could not finish this stage. Check its private notebook log."
            def fail(current):
                uncertain = False
                for worker in current["workers"]:
                    if worker["state"] not in WORKER_TERMINAL:
                        worker["state"] = "submission_uncertain" if worker.get("submissionAttempted") else "failed"
                        worker["stage"] = "Unconfirmed" if worker.get("submissionAttempted") else "Failed"
                        worker["error"] = message
                    uncertain |= worker["state"] == "submission_uncertain"
                current["state"] = "partial" if current["candidates"] else ("submission_uncertain" if uncertain else "failed")
                current["error"] = message
                current["selection"].update(status="unavailable", winnerCandidateId=None, reason=message)
            await self.update(job_id, fail)

    async def _run(self, job_id):
        job = await self.get(job_id)
        if job["enhancementStatus"] == "pending":
            if job["options"]["enhancePrompt"] and job["operation"] == "generate":
                await self.set_fields(job_id, state="enhancing")
                try:
                    result = await self.llm.enhance(job)
                    effective = result.get("effectivePrompt")
                    if not isinstance(effective, str) or not effective.strip() or len(effective) > 8000:
                        raise RouterError("Prompt assistant returned invalid text.")
                    await self.update(job_id, lambda item: item.update(effectivePrompt=effective,
                        enhancementStatus=result.get("status", "enhanced"), warnings=item["warnings"] + result.get("warnings", [])))
                except asyncio.CancelledError:
                    raise
                except Exception:
                    await self.update(job_id, lambda item: item.update(enhancementStatus="unavailable",
                        warnings=item["warnings"] + ["Prompt enhancement unavailable; the original prompt is used."]))
            else:
                await self.set_fields(job_id, enhancementStatus="disabled" if not job["options"]["enhancePrompt"] else "planned_with_edit")
        job = await self.get(job_id)
        prepared = None
        if job["operation"] == "edit":
            await self.set_fields(job_id, state="planning")
            source = await asyncio.to_thread(self.assets.path, job["sourceAssetId"])
            if job["editPlan"] is None:
                plan = await self.llm.plan_edit(job, source)
                plan.update(workingWidth=job["parameters"]["width"], workingHeight=job["parameters"]["height"])
                await self.set_fields(job_id, editPlan=plan, effectivePrompt=plan["positivePrompt"])
                job = await self.get(job_id)
            if job.get("preparedEdit"):
                prepared = await self._restore_prepared_edit(job["preparedEdit"], source)
            else:
                if any(worker.get("submissionAttempted") for worker in job["workers"]):
                    raise RouterError("Exact saved edit preparation is missing. Check accepted worker renders before creating a new edit.", 409, "edit_preparation_missing")
                mask = await asyncio.to_thread(self.assets.path, job["maskAssetId"]) if job["maskAssetId"] else None
                work_dir = self.config.root / "work" / job_id / "edit"
                prepared = await asyncio.to_thread(prepare_edit, source, mask, job["editPlan"], work_dir)
                if prepared.get("degradedMask"):
                    raise RouterError("Automatic selection could not find a reliable mask. Add or correct the selection in Edit image.", 422, "mask_required")
                manifest = await self._store_prepared_edit(prepared)
                warnings = prepared.get("warnings", []) + job["editPlan"].get("warnings", []) + ["Editing disables experimental sampler/attention acceleration to preserve patch compatibility."]
                await self.update(job_id, lambda item: item.update(preparedEdit=manifest, warnings=list(dict.fromkeys(item["warnings"] + warnings))))
        await self.set_fields(job_id, state="dispatching")
        probes = {item["workerId"]: item for item in await self.workers.probes()}
        job = await self.get(job_id)
        async def one(worker):
            record = next(item for item in job["workers"] if item["workerId"] == worker.worker_id)
            if record["state"] in WORKER_TERMINAL:
                return
            observed = probes[worker.worker_id]
            accepted_output = False
            async def change(fields, durable=True):
                def apply(current):
                    target = next(item for item in current["workers"] if item["workerId"] == worker.worker_id)
                    if current["state"] != "cancelled" and target["state"] not in WORKER_TERMINAL:
                        target.update(fields)
                return await self.update(job_id, apply, durable)
            try:
                if record.get("submissionAttempted"):
                    observed_runtime = observed.get("runtimeId", "")
                    if observed_runtime and observed_runtime != record["runtimeId"]:
                        raise WorkerFailure("Worker restarted after submission. Its previous render cannot be confirmed safely.", True)
                    if not observed_runtime:
                        known_prompt = bool(record.get("promptId"))
                        raise WorkerFailure("Worker runtime could not be authenticated; accepted IDs are preserved until it can be verified.",
                                            not known_prompt, resume_only=known_prompt)
                # Resumed accepted work follows its prompt instead of requiring
                # a catalog check that might change after submission.
                if not record.get("submissionAttempted"):
                    if not observed["online"]:
                        await change({"state": "skipped", "stage": "Unavailable", "error": observed["message"]})
                        return
                    params = job["parameters"]
                    if params["model"] not in observed["checkpoints"] or (params["lora"] and params["lora"] not in observed["loras"]):
                        await change({"state": "skipped", "stage": "Model unavailable", "error": "This worker does not have the selected checkpoint or LoRA."})
                        return
                    await change({"runtimeId": observed["runtimeId"]})
                    record = (await self.get(job_id))["workers"][job["workers"].index(record)]
                graph_params = copy.deepcopy(job["parameters"])
                extras = graph_params["speedExtras"]
                fooocus = False
                actual_positive = job["effectivePrompt"]
                actual_negative = job["editPlan"].get("negativePrompt", job["negativePrompt"]) if prepared else job["negativePrompt"]
                recorded = record.get("renderMetadata")
                if record.get("submissionAttempted"):
                    if not isinstance(recorded, dict):
                        raise WorkerFailure("Accepted render settings were not saved; its exact recipe cannot be confirmed.", True)
                    graph_params = copy.deepcopy(recorded["parameters"])
                    extras, fooocus = recorded["speedExtras"], recorded["fooocusInpaint"]
                    actual_positive, actual_negative = recorded["positivePrompt"], recorded["negativePrompt"]
                    graph = {}  # Recovery/follow never posts another graph.
                elif prepared:
                    graph_params.update(width=prepared["width"], height=prepared["height"])
                    source_name = await self.workers.upload(worker, prepared["sourcePath"], "source")
                    mask_name = await self.workers.upload(worker, prepared["maskPath"], "mask") if prepared.get("maskPath") else None
                    model_basename = graph_params["model"].replace("\\", "/").split("/")[-1].lower()
                    distilled = any(word in model_basename for word in ("lightning", "turbo", "hyper", "distill"))
                    known_recipe = model_basename == "waiillustrioussdxl_v170.safetensors"
                    requested_inpaint = job["options"].get("auxiliaryInpaint", True)
                    fooocus = requested_inpaint and bool(observed.get("capabilities", {}).get("fooocusInpaint")) and prepared["mode"] in {"replace", "outpaint"} and known_recipe and not distilled
                    if prepared["mode"] in {"replace", "outpaint"} and not fooocus:
                        message = (f"{worker.name}: stronger inpainting is off; using the ordinary same-checkpoint edit graph."
                                   if not requested_inpaint else f"{worker.name}: auxiliary inpaint patch unavailable or unsupported; using the ordinary same-checkpoint edit graph.")
                        await self.update(job_id, lambda item: item.update(warnings=item["warnings"] +
                            [message]))
                    graph = build_edit(graph_params, actual_positive, actual_negative,
                                       record["seed"], source_name, mask_name, prepared["mode"], prepared["denoise"], fooocus=fooocus)
                    extras = False
                else:
                    graph = build_generation(graph_params, actual_positive, actual_negative, record["seed"])
                if not record.get("submissionAttempted"):
                    render_metadata = {"parameters": copy.deepcopy(graph_params), "speedExtras": extras,
                        "fooocusInpaint": fooocus, "positivePrompt": actual_positive, "negativePrompt": actual_negative}
                    await change({"renderMetadata": render_metadata}, True)
                deadline = min(time.monotonic() + self.config.worker_timeout_seconds,
                               time.monotonic() + max(0.01, (job["deadlineMillis"] - now_ms()) / 1000))
                saved_output = record.get("acceptedOutput")
                if saved_output is not None:
                    accepted_output = True
                    if not isinstance(saved_output, dict) or not record.get("submissionAttempted"):
                        raise WorkerFailure("Saved accepted output metadata is invalid; another render will not be submitted.", resume_only=True)
                    images = [copy.deepcopy(saved_output)]
                else:
                    images = await self.workers.render(worker, record, graph, extras, change, deadline)
                    accepted_output = True
                await change({"stage": "Copying original"}, False)
                # Approved graphs have one SaveImage output. Do not turn an
                # unexpected worker graph into unbounded router storage work.
                if len(images) != 1:
                    raise WorkerFailure("Worker returned an unexpected number of images.")
                if saved_output is None:
                    descriptor = images[0]
                    if not isinstance(descriptor, dict):
                        raise WorkerFailure("Worker returned invalid accepted image metadata.", resume_only=True)
                    descriptor = {"filename": descriptor.get("filename"),
                                  "subfolder": descriptor.get("subfolder", ""),
                                  "type": descriptor.get("type", "output")}
                    if any(not isinstance(value, str) or len(value) > 240 for value in descriptor.values()):
                        raise WorkerFailure("Worker returned invalid accepted image metadata.", resume_only=True)
                    images = [descriptor]
                    # Freeze retrieval identity before any HTTP/local storage
                    # operation can fail. A retry copies this exact output.
                    await change({"acceptedOutput": copy.deepcopy(descriptor)}, True)
                path = self.config.root / "work" / job_id / worker.worker_id / "candidate.png"
                await self.workers.collect(worker, images[0], path)
                if prepared:
                    path = await asyncio.to_thread(finish_edit, prepared, path, path.with_name("finished.png"))
                asset = await asyncio.to_thread(self.assets.ingest, path)
                candidate = {"candidateId": f"{job_id}-{worker.worker_id}", "assetId": asset["assetId"],
                    "workerId": worker.worker_id, "workerName": worker.name, "seed": record["seed"],
                    "width": asset["width"], "height": asset["height"], "model": graph_params["model"],
                    "lora": graph_params["lora"], "loraStrength": graph_params["loraStrength"],
                    "steps": 18 if graph_params["preset"] == "fast" else 24, "cfg": 6.5,
                    "sampler": "dpmpp_2m", "scheduler": "karras", "speedExtras": extras,
                    "originalPrompt": job["originalPrompt"], "effectivePrompt": actual_positive,
                    "negativePrompt": actual_negative,
                    "sourceAssetId": job["sourceAssetId"], "editInstruction": job["editInstruction"],
                    "editMode": prepared["mode"] if prepared else None, "fooocusInpaint": fooocus,
                    "workingWidth": graph_params["width"], "workingHeight": graph_params["height"],
                    "editPreparation": copy.deepcopy(job.get("preparedEdit", {}).get("metadata")) if prepared else None}
                def finish(current):
                    target = next(item for item in current["workers"] if item["workerId"] == worker.worker_id)
                    if current["state"] == "cancelled":
                        return
                    if not any(item["candidateId"] == candidate["candidateId"] for item in current["candidates"]):
                        current["candidates"].append(candidate)
                    target.update(state="complete", stage="Done", stepsDone=target["stepsTotal"], error=None, resumeOnly=False)
                await self.update(job_id, finish)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                current = await self.get(job_id)
                durable_record = next(item for item in current["workers"] if item["workerId"] == worker.worker_id)
                known_prompt = isinstance(durable_record.get("promptId"), str) and bool(durable_record["promptId"])
                uncertain = isinstance(error, WorkerFailure) and error.uncertain
                resume_only = accepted_output or (isinstance(error, WorkerFailure) and error.resume_only)
                # Unexpected local failures while following an already-known
                # prompt are not evidence that its render should be repeated.
                if durable_record.get("submissionAttempted"):
                    if not isinstance(error, WorkerFailure):
                        uncertain, resume_only = not known_prompt, known_prompt
                    elif resume_only:
                        uncertain, resume_only = not known_prompt, known_prompt
                message = str(error) if isinstance(error, (WorkerFailure, RouterError)) else "Worker stage failed; check the router notebook log."
                await change({"state": "submission_uncertain" if uncertain else "failed", "stage": "Unconfirmed" if uncertain else "Failed", "error": message, "resumeOnly": resume_only})
        await self.set_fields(job_id, state="rendering")
        await asyncio.gather(*(one(worker) for worker in self.config.workers))
        job = await self.get(job_id)
        if not job["candidates"]:
            uncertain = any(item["state"] == "submission_uncertain" for item in job["workers"])
            await self.set_fields(job_id, state="submission_uncertain" if uncertain else "failed",
                error="No worker produced a stored image. See worker status for the reason.",
                selection={"status": "unavailable", "winnerCandidateId": None, "reason": "No candidates", "scores": [],
                           "reviewerModel": "", "reviewerRevision": ""})
            return
        selection = {"status": "disabled", "winnerCandidateId": None, "reason": "Automatic review is off.", "scores": [], "reviewerModel": "", "reviewerRevision": ""}
        if job["options"]["reviewCandidates"]:
            await self.set_fields(job_id, state="reviewing")
            try:
                paths = {candidate["assetId"]: await asyncio.to_thread(self.assets.path, candidate["assetId"]) for candidate in job["candidates"]}
                if job["sourceAssetId"]:
                    paths[job["sourceAssetId"]] = await asyncio.to_thread(self.assets.path, job["sourceAssetId"])
                selection = await self.llm.review(job, job["candidates"], paths)
                available = {item["candidateId"] for item in job["candidates"]}
                if selection.get("status") == "selected" and selection.get("winnerCandidateId") not in available:
                    raise RouterError("Reviewer named an unavailable candidate.")
                if selection.get("status") not in {"selected", "unavailable"}:
                    raise RouterError("Reviewer returned an invalid selection status.")
                if selection["status"] != "selected":
                    selection["winnerCandidateId"] = None
            except asyncio.CancelledError:
                raise
            except Exception:
                selection = {"status": "unavailable", "winnerCandidateId": None,
                    "reason": "Review unavailable; these candidates have not been automatically ranked.", "scores": [],
                    "reviewerModel": self.config.llm_model, "reviewerRevision": self.config.llm_revision}
        success = sum(worker["state"] == "complete" for worker in job["workers"])
        warning = ((f"Selected from {success} of {len(job['workers'])} workers." if selection["status"] == "selected"
                   else f"{success} of {len(job['workers'])} workers produced stored candidates.") if success < len(job["workers"]) else None)
        await self.update(job_id, lambda current: current.update(state="complete" if success == len(job["workers"]) else "partial",
            selection=selection, warnings=current["warnings"] + ([warning] if warning else []), error=None))
        # Temporary graph/upload/crop files are no longer needed. Durable source
        # and candidate assets remain, including alternatives hidden on the phone.
        await asyncio.to_thread(shutil.rmtree, self.config.root / "work" / job_id, True)

    async def cancel(self, job_id):
        job = await self.get(job_id)
        if job["state"] in TERMINAL:
            return job
        await self.set_fields(job_id, state="cancelled", error="Cancelled by the phone; remote cancellation is best-effort.")
        task = self.tasks.get(job_id)
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        job = await self.get(job_id)
        for worker in self.config.workers:
            record = next(item for item in job["workers"] if item["workerId"] == worker.worker_id)
            if record["state"] in WORKER_TERMINAL:
                continue
            cancelled = await self.workers.cancel(worker, record)
            uncertain = record.get("submissionAttempted") and not cancelled
            def apply(current):
                target = next(item for item in current["workers"] if item["workerId"] == worker.worker_id)
                target.update(state="submission_uncertain" if uncertain else "cancelled",
                              stage="Remote cancellation unconfirmed" if uncertain else "Cancelled")
            await self.update(job_id, apply)
        return await self.get(job_id)

    async def retry(self, job_id, request_id=None):
        identifier(job_id, "Job ID")
        if request_id is not None:
            identifier(request_id, "Retry request ID")
        def reset(job):
            if job["state"] not in TERMINAL:
                raise RouterError("Wait for the current router job to finish.", 409)
            if any(worker["state"] == "submission_uncertain" for worker in job["workers"]):
                raise RouterError("A worker submission is still uncertain. Check its notebook before starting another render.", 409, "submission_uncertain")
            retry_ids = {worker["workerId"] for worker in job["workers"] if worker["state"] in {"failed", "skipped", "cancelled"}}
            if not retry_ids:
                raise RouterError("There are no confirmed failed workers to retry.", 409)
            for worker in job["workers"]:
                if worker["workerId"] in retry_ids:
                    legacy_accepted = "resumeOnly" not in worker and worker.get("submissionAttempted")
                    if worker.get("resumeOnly") or legacy_accepted:
                        if not worker.get("submissionAttempted") or not all(isinstance(worker.get(key), str) and worker[key]
                                for key in ("promptId", "runtimeId", "requestId", "clientId")):
                            raise RouterError("Saved accepted render identity is missing. Another render will not be submitted.", 409, "submission_uncertain")
                        worker.update(state="pending", stage="Resuming accepted result", error=None, resumeOnly=True)
                    else:
                        worker.pop("acceptedOutput", None)
                        worker.update(requestId=str(uuid.uuid4()), clientId=f"router-{uuid.uuid4()}", submissionAttempted=False,
                                      promptId=None, runtimeId="", state="pending", stage="Waiting", error=None, stepsDone=0, stepsTotal=0, resumeOnly=False)
            job.update(state="accepted", error=None, deadlineMillis=now_ms() + self.config.job_timeout_seconds * 1000,
                selection={"status": "pending", "winnerCandidateId": None, "reason": "", "scores": [],
                           "reviewerModel": "", "reviewerRevision": ""})
        async with self._submit_lock:
            retried, created = await asyncio.to_thread(self.journal.retry, job_id, request_id, reset)
            if retried["state"] not in TERMINAL:
                self.schedule(job_id)
            if created:
                for listener in self.listeners.get(job_id, set()):
                    listener.set()
            return retried

    async def begin_download(self, body):
        if not isinstance(body, dict) or body.get("kind") not in {"checkpoint", "lora"}:
            raise RouterError("Choose checkpoint or lora for the model download.")
        version = body.get("modelVersionId")
        if not isinstance(version, str) or not version.isdigit() or len(version) > 20:
            raise RouterError("Use a numeric Civitai model-version ID.")
        selected = body.get("workerId", "all")
        targets = [worker for worker in self.config.workers if selected == "all" or worker.worker_id == selected]
        if not targets:
            raise RouterError("That worker is not configured on this router.")
        download = {"jobId": str(uuid.uuid4()), "status": "running", "progress": 0.0, "filename": None,
                    "kind": body["kind"], "error": None, "workers": []}
        await asyncio.to_thread(self.journal.put_download, download)
        for worker in targets:
            try:
                result = await self.workers.json(worker, "POST", "/phone-studio/download-model", body={"modelVersionId": version, "kind": body["kind"]}, timeout=20)
                upstream_id = result.get("jobId")
                if not isinstance(upstream_id, str) or not upstream_id:
                    raise WorkerFailure("Worker returned no download ID.")
                identifier(upstream_id, "Worker download ID")
                download["workers"].append({"workerId": worker.worker_id, "name": worker.name, "jobId": upstream_id, "status": "running", "progress": 0.0, "error": None})
            except (WorkerFailure, RouterError) as error:
                download["workers"].append({"workerId": worker.worker_id, "name": worker.name, "jobId": None, "status": "failed", "progress": 0.0, "error": str(error)})
        self._summarize_download(download)
        await asyncio.to_thread(self.journal.put_download, download)
        return download

    @staticmethod
    def _download_progress(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return 0.0
        return min(100.0, max(0.0, float(value)))

    @classmethod
    def _summarize_download(cls, download):
        """Keep the existing worker/phone percentage and terminal-status contract."""
        records = download["workers"]
        for record in records:
            status = record.get("status")
            if status in {"done", "complete"}:
                record.update(status="complete", progress=100.0)
            elif status in {"error", "failed"}:
                record["status"] = "failed"
                record["progress"] = cls._download_progress(record.get("progress"))
            else:
                record["progress"] = cls._download_progress(record.get("progress"))
        done = sum(item["status"] == "complete" for item in records)
        errors = sum(item["status"] == "failed" for item in records)
        download.update(status="complete" if done == len(records) and records else
                        ("failed" if errors == len(records) and records else
                         ("partial" if done + errors == len(records) and records else "running")),
                        progress=sum(item["progress"] for item in records) / max(1, len(records)),
                        filename=next((item.get("filename") for item in records if item.get("filename")), None),
                        error="Some workers could not download this model." if errors else None)

    async def download_status(self, download_id):
        download = await asyncio.to_thread(self.journal.download, identifier(download_id, "Download ID"))
        for record in download["workers"]:
            if record["status"] in {"done", "error", "complete", "failed"} or not record.get("jobId"):
                continue
            worker = next(item for item in self.config.workers if item.worker_id == record["workerId"])
            try:
                status = await self.workers.json(worker, "GET", f"/phone-studio/downloads/{record['jobId']}", timeout=10)
                record.update(status=status.get("status", "unknown"), progress=self._download_progress(status.get("progress")),
                              filename=status.get("filename"), error="Worker download failed." if status.get("error") else None)
            except WorkerFailure:
                record["error"] = "Download status unavailable; the worker may still be downloading."
        self._summarize_download(download)
        await asyncio.to_thread(self.journal.put_download, download)
        return download
