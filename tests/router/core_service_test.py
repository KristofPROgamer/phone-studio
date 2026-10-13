"""Mock workers and mock LLM only; exercises the real router state/storage pipeline."""
import asyncio
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from router.config import Config, RouterError, WorkerConfig
from router.service import RouterService
from router.workers import WorkerFailure


class FakeLLM:
    def __init__(self):
        self.reviews = []
        self.bad_winner = False
        self.plan = {"mode": "global", "positivePrompt": "blue sky, two cats", "negativePrompt": "text", "denoise": 0.4, "warnings": []}

    async def health(self):
        return {"ready": True, "model": "mock-vision", "revision": "mock-revision", "degraded": False, "message": "Ready"}

    async def enhance(self, request):
        return {"effectivePrompt": "2cats, garden, blue sky", "status": "enhanced", "warnings": []}

    async def plan_edit(self, request, path):
        return copy.deepcopy(self.plan)

    async def review(self, request, candidates, paths):
        self.reviews.append((copy.deepcopy(request), copy.deepcopy(candidates)))
        return {"status": "selected", "winnerCandidateId": "missing" if self.bad_winner else candidates[-1]["candidateId"],
                "reason": "Requested subjects are clearest.", "scores": [], "reviewerModel": "mock-vision", "reviewerRevision": "mock-revision"}

    async def close(self):
        pass


class FakeWorkers:
    def __init__(self, config):
        self.config = config
        self.calls = []
        self.failures = {}
        self.gates = {}
        self.observed = {}
        self.runtime = "runtime-1"
        self.model = "model.safetensors"
        self.capabilities = {}

    async def start(self):
        pass

    async def close(self):
        pass

    async def probes(self, **kwargs):
        return [{"workerId": item.worker_id, "name": item.name, "online": True, "checkpointCount": 1,
                 "message": "Ready", "runtimeId": self.runtime, "checkpoints": [self.model], "loras": [],
                 "capabilities": copy.deepcopy(self.capabilities), "defaultCheckpoint": self.model} for item in self.config.workers]

    async def render(self, worker, record, graph, extras, on_change, deadline):
        self.calls.append((worker.worker_id, copy.deepcopy(record), graph, extras))
        await on_change({"submissionAttempted": True, "promptId": "prompt-" + worker.worker_id,
                         "state": "rendering", "stepsDone": 1, "stepsTotal": 24}, True)
        if worker.worker_id in self.gates:
            await self.gates[worker.worker_id].wait()
        failure = self.failures.get(worker.worker_id)
        if failure:
            raise failure
        return [{"filename": "result.png", "subfolder": "", "type": "output"}]

    async def collect(self, worker, descriptor, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        color = {"w1": "red", "w2": "blue", "w3": "green"}[worker.worker_id]
        # Fake dimensions match the ordinary 768x1024 render; editing assertions
        # use the portrait source so its working canvas has this same shape.
        Image.new("RGB", (768, 1024), color).save(target)
        return target

    async def upload(self, worker, path, suffix):
        assert Path(path).is_file()
        return suffix + ".png"

    async def cancel(self, worker, record):
        return True


class RouterServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.config = Config(root / "local", root / "drive", "secret",
            workers=tuple(WorkerConfig(f"w{number}", f"Worker {number}", "https://worker.invalid", studio_token="worker-secret") for number in (1, 2, 3)),
            disk_reserve_bytes=0, job_timeout_seconds=60, worker_timeout_seconds=30)
        self.workers, self.llm = FakeWorkers(self.config), FakeLLM()
        self.service = RouterService(self.config, workers=self.workers, llm=self.llm)
        await self.service.start()

    async def asyncTearDown(self):
        await self.service.close()
        self.temp.cleanup()

    def body(self, **kwargs):
        body = {"schemaVersion": 2, "clientId": "phone", "requestId": "request1", "operation": "generate",
            "originalPrompt": "two cats in a garden", "negativePrompt": "text",
            "parameters": {"model": "model.safetensors", "baseSeed": 1001}}
        body.update(kwargs)
        return body

    async def finished(self, job_id):
        for _ in range(500):
            job = await self.service.get(job_id)
            if job["state"] in {"complete", "partial", "failed", "cancelled", "submission_uncertain"}:
                return job
            await asyncio.sleep(0.01)
        self.fail("Mock job never became terminal")

    async def test_three_workers_original_prompt_review_and_durable_candidates(self):
        accepted = await self.service.submit(self.body())
        result = await self.finished(accepted["jobId"])
        self.assertEqual(result["state"], "complete")
        self.assertEqual([item["seed"] for item in result["workers"]], [1001, 1002, 1003])
        self.assertEqual(len(result["candidates"]), 3)
        self.assertEqual(self.llm.reviews[0][0]["originalPrompt"], "two cats in a garden")
        self.assertEqual(result["effectivePrompt"], "2cats, garden, blue sky")
        self.assertEqual(result["selection"]["winnerCandidateId"], result["candidates"][-1]["candidateId"])
        self.assertTrue(all((self.config.drive / "assets" / (candidate["assetId"] + ".png")).is_file() for candidate in result["candidates"]))
        replay = await self.service.submit(self.body())
        self.assertEqual(replay["jobId"], accepted["jobId"])
        self.assertEqual(len(self.workers.calls), 3)

    async def test_partial_retry_only_failed_and_retry_key_idempotent(self):
        self.workers.failures["w2"] = WorkerFailure("Confirmed render failure")
        accepted = await self.service.submit(self.body())
        result = await self.finished(accepted["jobId"])
        self.assertEqual(result["state"], "partial")
        old_assets = {item["assetId"] for item in result["candidates"]}
        self.workers.failures.clear()
        retried = await self.service.retry(result["jobId"], "retry-once")
        self.assertEqual(retried["jobId"], accepted["jobId"])
        done = await self.finished(retried["jobId"])
        self.assertEqual(done["state"], "complete")
        self.assertEqual([item[0] for item in self.workers.calls].count("w2"), 2)
        self.assertEqual([item[0] for item in self.workers.calls].count("w1"), 1)
        self.assertTrue(old_assets <= {item["assetId"] for item in done["candidates"]})
        replay = await self.service.retry(result["jobId"], "retry-once")
        self.assertEqual(replay["revision"], done["revision"])
        self.assertEqual(len(self.workers.calls), 4)

    async def test_uncertain_worker_is_never_authorized_for_retry(self):
        self.workers.failures["w2"] = WorkerFailure("Receipt uncertain", True)
        accepted = await self.service.submit(self.body())
        result = await self.finished(accepted["jobId"])
        self.assertEqual(result["workers"][1]["state"], "submission_uncertain")
        with self.assertRaises(RouterError) as caught:
            await self.service.retry(result["jobId"], "retry1")
        self.assertEqual(caught.exception.code, "submission_uncertain")
        self.assertEqual(len(self.workers.calls), 3)

    async def test_partial_finished_output_retry_only_recopies_third_worker_preserving_accepted_recipe(self):
        collect = self.workers.collect
        render = self.workers.render
        async def image_metadata(worker, record, graph, extras, on_change, deadline):
            result = await render(worker, record, graph, extras, on_change, deadline)
            result[0]["privateMetadata"] = "must-not-be-forwarded"
            return result
        self.workers.render = image_metadata
        copies = []
        broken = True
        async def sometimes_collect(worker, descriptor, target):
            copies.append(worker.worker_id)
            if worker.worker_id == "w3" and broken:
                # The older transport used a definite WorkerFailure here;
                # service must still recognize failure after accepted output.
                raise WorkerFailure("Lost contact while copying a finished image.")
            return await collect(worker, descriptor, target)
        self.workers.collect = sometimes_collect
        accepted = await self.service.submit(self.body())
        partial = await self.finished(accepted["jobId"])
        self.assertEqual(partial["state"], "partial")
        failed = copy.deepcopy(partial["workers"][2])
        self.assertTrue(failed["resumeOnly"])
        self.assertEqual(failed["acceptedOutput"]["filename"], "result.png")
        self.assertEqual(set(failed["acceptedOutput"]), {"filename", "subfolder", "type"})
        self.assertNotIn("must-not-be-forwarded", str(partial))
        preserved = copy.deepcopy(partial["workers"][:2])
        assets = {item["assetId"] for item in partial["candidates"]}
        broken = False
        await self.service.retry(partial["jobId"], "copy-third-output")
        done = await self.finished(partial["jobId"])
        self.assertEqual(done["state"], "complete")
        self.assertEqual(done["workers"][:2], preserved)
        for key in ("promptId", "runtimeId", "requestId", "clientId", "submissionAttempted", "renderMetadata", "acceptedOutput"):
            self.assertEqual(done["workers"][2][key], failed[key])
        self.assertEqual([item[0] for item in self.workers.calls], ["w1", "w2", "w3"])
        self.assertEqual(copies, ["w1", "w2", "w3", "w3"])
        self.assertTrue(assets <= {item["assetId"] for item in done["candidates"]})

    async def test_local_copy_and_asset_ingest_failure_cannot_authorize_another_accepted_render(self):
        collect = self.workers.collect
        ingest = self.service.assets.ingest
        for failure_stage in ("local_copy", "asset_ingest"):
            with self.subTest(stage=failure_stage):
                broken = True
                async def local_collect(worker, descriptor, target):
                    if worker.worker_id == "w3" and broken and failure_stage == "local_copy":
                        raise OSError("synthetic local storage failure")
                    return await collect(worker, descriptor, target)
                def local_ingest(path, *args, **kwargs):
                    if Path(path).parent.name == "w3" and broken and failure_stage == "asset_ingest":
                        raise ValueError("synthetic unreadable image")
                    return ingest(path, *args, **kwargs)
                self.workers.collect = local_collect
                self.service.assets.ingest = local_ingest
                before = len(self.workers.calls)
                accepted = await self.service.submit(self.body(requestId="post-render-" + failure_stage))
                partial = await self.finished(accepted["jobId"])
                self.assertTrue(partial["workers"][2]["resumeOnly"])
                prompt_id = partial["workers"][2]["promptId"]
                broken = False
                await self.service.retry(partial["jobId"], "recover-" + failure_stage)
                done = await self.finished(partial["jobId"])
                self.assertEqual(done["state"], "complete")
                self.assertEqual(len(self.workers.calls), before + 3)
                self.assertEqual(done["workers"][2]["promptId"], prompt_id)

    async def test_known_accepted_follow_retry_preserves_ids_and_follows_empty_graph(self):
        render = self.workers.render
        broken = True
        async def follow(worker, record, graph, extras, on_change, deadline):
            if worker.worker_id == "w3" and broken:
                self.workers.calls.append((worker.worker_id, copy.deepcopy(record), graph, extras))
                await on_change({"submissionAttempted": True, "promptId": "accepted-w3"}, True)
                raise WorkerFailure("Worker credentials were rejected while following accepted history.", resume_only=True)
            return await render(worker, record, graph, extras, on_change, deadline)
        self.workers.render = follow
        accepted = await self.service.submit(self.body())
        partial = await self.finished(accepted["jobId"])
        failed = copy.deepcopy(partial["workers"][2])
        self.assertTrue(failed["resumeOnly"])
        self.assertNotIn("acceptedOutput", failed)
        broken = False
        await self.service.retry(partial["jobId"], "follow-third")
        done = await self.finished(partial["jobId"])
        self.assertEqual(done["state"], "complete")
        retried = self.workers.calls[-1]
        self.assertEqual(retried[2], {})
        for key in ("promptId", "runtimeId", "requestId", "clientId", "submissionAttempted", "renderMetadata"):
            self.assertEqual(retried[1][key], failed[key])

    async def test_resume_only_retry_rejects_missing_accepted_identity(self):
        self.workers.failures["w3"] = WorkerFailure("synthetic follow failure", resume_only=True)
        accepted = await self.service.submit(self.body())
        partial = await self.finished(accepted["jobId"])
        await self.service.update(partial["jobId"], lambda item: item["workers"][2].update(promptId=None))
        with self.assertRaises(RouterError) as caught:
            await self.service.retry(partial["jobId"], "invalid-resume")
        self.assertEqual(caught.exception.code, "submission_uncertain")
        self.assertEqual(len(self.workers.calls), 3)

    async def test_unexpected_post_acceptance_failure_uses_current_durable_identity(self):
        render = self.workers.render
        async def failed_after_acceptance(worker, record, graph, extras, on_change, deadline):
            if worker.worker_id == "w3":
                self.workers.calls.append((worker.worker_id, copy.deepcopy(record), graph, extras))
                await on_change({"submissionAttempted": True, "promptId": "durably-accepted-w3"}, True)
                raise RuntimeError("synthetic post-publication/observer failure")
            return await render(worker, record, graph, extras, on_change, deadline)
        self.workers.render = failed_after_acceptance
        accepted = await self.service.submit(self.body())
        partial = await self.finished(accepted["jobId"])
        self.assertTrue(partial["workers"][2]["resumeOnly"])
        self.assertEqual(partial["workers"][2]["promptId"], "durably-accepted-w3")
        self.workers.render = render
        await self.service.retry(partial["jobId"], "resume-after-observer-failure")
        done = await self.finished(partial["jobId"])
        self.assertEqual(done["state"], "complete")
        self.assertEqual(self.workers.calls[-1][2], {})
        self.assertEqual(self.workers.calls[-1][1]["promptId"], "durably-accepted-w3")

    async def test_queued_publication_failure_with_unknown_durable_prompt_blocks_retry(self):
        render = self.workers.render
        async def lost_publication(worker, record, graph, extras, on_change, deadline):
            if worker.worker_id == "w3":
                self.workers.calls.append((worker.worker_id, copy.deepcopy(record), graph, extras))
                await on_change({"submissionAttempted": True}, True)
                raise WorkerFailure("Accepted queued publication failed", True, resume_only=True)
            return await render(worker, record, graph, extras, on_change, deadline)
        self.workers.render = lost_publication
        accepted = await self.service.submit(self.body())
        partial = await self.finished(accepted["jobId"])
        self.assertEqual(partial["workers"][2]["state"], "submission_uncertain")
        self.assertIsNone(partial["workers"][2]["promptId"])
        with self.assertRaises(RouterError) as caught:
            await self.service.retry(partial["jobId"], "unknown-queued-publication")
        self.assertEqual(caught.exception.code, "submission_uncertain")
        self.assertEqual(len(self.workers.calls), 3)

    async def test_legacy_failed_accepted_record_follows_existing_prompt_before_new_render(self):
        self.workers.failures["w3"] = WorkerFailure("Legacy ambiguous failure")
        accepted = await self.service.submit(self.body())
        partial = await self.finished(accepted["jobId"])
        await self.service.update(partial["jobId"], lambda item: item["workers"][2].pop("resumeOnly", None))
        legacy = await self.service.get(partial["jobId"])
        retained = copy.deepcopy(legacy["workers"][2])
        self.workers.failures.clear()
        await self.service.retry(legacy["jobId"], "legacy-follow-first")
        done = await self.finished(legacy["jobId"])
        self.assertEqual(done["state"], "complete")
        self.assertEqual(self.workers.calls[-1][2], {})
        for key in ("promptId", "runtimeId", "requestId", "clientId", "submissionAttempted", "renderMetadata"):
            self.assertEqual(self.workers.calls[-1][1][key], retained[key])

    async def test_legacy_failed_record_with_unknown_accepted_prompt_remains_blocked(self):
        self.workers.failures["w3"] = WorkerFailure("Legacy ambiguous failure")
        accepted = await self.service.submit(self.body())
        partial = await self.finished(accepted["jobId"])
        def legacy_unknown(item):
            worker = item["workers"][2]
            worker.pop("resumeOnly", None)
            worker["promptId"] = None
        await self.service.update(partial["jobId"], legacy_unknown)
        with self.assertRaises(RouterError) as caught:
            await self.service.retry(partial["jobId"], "legacy-unknown-accepted")
        self.assertEqual(caught.exception.code, "submission_uncertain")
        self.assertEqual(len(self.workers.calls), 3)

    async def test_catalog_timeout_cannot_hide_authenticated_worker_restart_before_output_copy(self):
        collect = self.workers.collect
        async def failed_copy(worker, descriptor, target):
            if worker.worker_id == "w3":
                raise WorkerFailure("synthetic image retrieval failure")
            return await collect(worker, descriptor, target)
        self.workers.collect = failed_copy
        accepted = await self.service.submit(self.body())
        partial = await self.finished(accepted["jobId"])
        known = partial["workers"][2]
        probes = self.workers.probes
        async def restarted_but_catalog_slow(**kwargs):
            results = await probes(**kwargs)
            results[2].update(online=False, runtimeId="new-authenticated-runtime", probeStage="catalog_timeout")
            return results
        self.workers.probes = restarted_but_catalog_slow
        self.workers.collect = lambda *a, **k: self.fail("Mismatched runtime must not retrieve old descriptor")
        await self.service.retry(partial["jobId"], "runtime-conflict")
        result = await self.finished(partial["jobId"])
        self.assertEqual(result["workers"][2]["state"], "submission_uncertain")
        self.assertEqual(result["workers"][2]["promptId"], known["promptId"])
        self.assertEqual(result["workers"][2]["acceptedOutput"], known["acceptedOutput"])
        self.assertEqual(len(self.workers.calls), 3)

    async def test_unreachable_known_runtime_preserves_output_until_matching_health_returns(self):
        collect = self.workers.collect
        async def failed_copy(worker, descriptor, target):
            if worker.worker_id == "w3":
                raise WorkerFailure("synthetic image retrieval failure")
            return await collect(worker, descriptor, target)
        self.workers.collect = failed_copy
        accepted = await self.service.submit(self.body())
        partial = await self.finished(accepted["jobId"])
        known = copy.deepcopy(partial["workers"][2])
        probes = self.workers.probes
        async def unreachable(**kwargs):
            results = await probes(**kwargs)
            results[2].update(online=False, runtimeId="")
            return results
        self.workers.probes = unreachable
        self.workers.collect = lambda *a, **k: self.fail("Unverified runtime must not retrieve output")
        await self.service.retry(partial["jobId"], "unreachable-runtime")
        still_partial = await self.finished(partial["jobId"])
        self.assertTrue(still_partial["workers"][2]["resumeOnly"])
        self.assertIn("authenticated", still_partial["workers"][2]["error"])
        self.workers.probes, self.workers.collect = probes, collect
        await self.service.retry(partial["jobId"], "runtime-returns")
        done = await self.finished(partial["jobId"])
        self.assertEqual(done["state"], "complete")
        for key in ("promptId", "runtimeId", "requestId", "clientId", "submissionAttempted", "acceptedOutput", "renderMetadata"):
            self.assertEqual(done["workers"][2][key], known[key])
        self.assertEqual(len(self.workers.calls), 3)

    async def test_edit_output_retrieval_retry_reuses_exact_prepared_assets_without_render_or_replanning(self):
        source, mask = Path(self.temp.name) / "source.png", Path(self.temp.name) / "mask.png"
        Image.new("RGB", (384, 512), "yellow").save(source)
        Image.new("L", (384, 512), 255).save(mask)
        source_asset, mask_asset = self.service.assets.ingest(source), self.service.assets.ingest(mask, "mask")
        self.llm.plan.update(mode="replace")
        collect = self.workers.collect
        async def failed_copy(worker, descriptor, target):
            if worker.worker_id == "w3":
                raise WorkerFailure("synthetic image retrieval failure")
            return await collect(worker, descriptor, target)
        self.workers.collect = failed_copy
        accepted = await self.service.submit(self.body(operation="edit", sourceAssetId=source_asset["assetId"],
            maskAssetId=mask_asset["assetId"], editInstruction="replace the sky"))
        partial = await self.finished(accepted["jobId"])
        manifest = copy.deepcopy(partial["preparedEdit"])
        self.workers.collect = collect
        with patch("router.service.prepare_edit", side_effect=AssertionError("Exact saved preparation must be reused")), \
             patch.object(self.llm, "plan_edit", side_effect=AssertionError("Saved edit must not be replanned")), \
             patch.object(self.workers, "render", side_effect=AssertionError("Accepted output must not render again")):
            await self.service.retry(partial["jobId"], "copy-accepted-edit")
            done = await self.finished(partial["jobId"])
        self.assertEqual(done["state"], "complete")
        self.assertEqual(done["preparedEdit"], manifest)
        self.assertTrue(all(candidate["sourceAssetId"] == source_asset["assetId"] for candidate in done["candidates"]))
        self.assertEqual(done["workers"][2]["renderMetadata"], partial["workers"][2]["renderMetadata"])
        self.assertEqual(len(self.workers.calls), 3)

    async def test_third_worker_rejoin_retries_only_confirmed_failure_preserving_accepted_results(self):
        self.workers.failures["w3"] = WorkerFailure("Confirmed third-worker render failure")
        accepted = await self.service.submit(self.body())
        partial = await self.finished(accepted["jobId"])
        self.assertEqual(partial["state"], "partial")
        retained_workers = copy.deepcopy(partial["workers"][:2])
        retained_assets = {item["assetId"] for item in partial["candidates"]}
        original_probes = self.workers.probes
        async def rejoined(**kwargs):
            results = await original_probes(**kwargs)
            results[2]["runtimeId"] = "third-worker-new-runtime"
            return results
        self.workers.probes = rejoined
        self.workers.failures.clear()
        await self.service.retry(partial["jobId"], "third-worker-rejoin")
        done = await self.finished(partial["jobId"])
        self.assertEqual(done["state"], "complete")
        self.assertEqual(done["workers"][:2], retained_workers)
        self.assertTrue(retained_assets <= {item["assetId"] for item in done["candidates"]})
        # Independent worker submissions may reach the transport in any order.
        self.assertCountEqual([item[0] for item in self.workers.calls], ["w1", "w2", "w3", "w3"])
        self.assertEqual(self.workers.calls[-1][0], "w3")
        self.assertEqual(self.workers.calls[-1][1]["runtimeId"], "third-worker-new-runtime")
        self.assertEqual(done["jobId"], accepted["jobId"])
        self.assertEqual(len(self.llm.reviews[-1][1]), 3)

    async def test_invalid_winner_and_review_disabled_do_not_invent_best(self):
        self.llm.bad_winner = True
        accepted = await self.service.submit(self.body())
        result = await self.finished(accepted["jobId"])
        self.assertEqual(result["selection"]["status"], "unavailable")
        self.assertIsNone(result["selection"]["winnerCandidateId"])
        self.assertEqual(len(result["candidates"]), 3)
        accepted = await self.service.submit(self.body(requestId="request2", options={"enhancePrompt": False, "reviewCandidates": False}))
        result = await self.finished(accepted["jobId"])
        self.assertEqual(result["selection"]["status"], "disabled")
        self.assertIsNone(result["selection"]["winnerCandidateId"])
        self.assertEqual(result["effectivePrompt"], result["originalPrompt"])

    async def test_edit_source_is_preserved_and_acceleration_is_disabled(self):
        source = Path(self.temp.name) / "source.png"
        Image.new("RGB", (384, 512), "yellow").save(source)
        asset = self.service.assets.ingest(source)
        accepted = await self.service.submit(self.body(operation="edit", sourceAssetId=asset["assetId"], editInstruction="make the sky blue"))
        result = await self.finished(accepted["jobId"])
        self.assertEqual(result["state"], "complete")
        self.assertTrue(all(call[3] is False for call in self.workers.calls))
        self.assertTrue(all(candidate["speedExtras"] is False for candidate in result["candidates"]))
        self.assertTrue(all((candidate["width"], candidate["height"]) == (384, 512) for candidate in result["candidates"]))
        with Image.open(self.service.assets.path(asset["assetId"])) as saved:
            self.assertEqual(saved.getpixel((0, 0)), (255, 255, 0))

    async def test_failed_automatic_mask_reports_correction_before_dispatch(self):
        source = Path(self.temp.name) / "source.png"
        Image.new("RGB", (384, 512), "yellow").save(source)
        asset = self.service.assets.ingest(source)
        self.llm.plan.update(mode="replace", boxes=[[0.1, 0.1, 0.5, 0.5]], points=[])
        accepted = await self.service.submit(self.body(operation="edit", sourceAssetId=asset["assetId"], editInstruction="replace the hat"))
        result = await self.finished(accepted["jobId"])
        self.assertEqual(result["state"], "failed")
        self.assertIn("Paint or correct", result["error"])
        self.assertEqual(self.workers.calls, [])

    async def test_cancel_is_terminal_and_does_not_forget_submission(self):
        for worker in self.config.workers:
            self.workers.gates[worker.worker_id] = asyncio.Event()
        accepted = await self.service.submit(self.body())
        for _ in range(200):
            if len(self.workers.calls) == 3:
                break
            await asyncio.sleep(0.01)
        cancelled = await self.service.cancel(accepted["jobId"])
        self.assertEqual(cancelled["state"], "cancelled")
        self.assertTrue(all(worker["state"] == "cancelled" for worker in cancelled["workers"]))
        self.assertTrue(all(worker["submissionAttempted"] for worker in cancelled["workers"]))

    async def test_stronger_inpaint_off_never_applies_patch_even_when_supported(self):
        source = Path(self.temp.name) / "source.png"
        mask_file = Path(self.temp.name) / "mask.png"
        Image.new("RGB", (384, 512), "yellow").save(source)
        Image.new("L", (384, 512), 255).save(mask_file)
        source_asset = self.service.assets.ingest(source)
        mask_asset = self.service.assets.ingest(mask_file, "mask")
        self.workers.model = "waiIllustriousSDXL_v170.safetensors"
        self.workers.capabilities = {"fooocusInpaint": True}
        self.llm.plan.update(mode="replace")
        body = self.body(operation="edit", sourceAssetId=source_asset["assetId"], maskAssetId=mask_asset["assetId"],
                         editInstruction="replace the sky", options={"auxiliaryInpaint": False})
        body["parameters"]["model"] = self.workers.model
        accepted = await self.service.submit(body)
        result = await self.finished(accepted["jobId"])
        self.assertEqual(result["state"], "complete")
        self.assertTrue(all(candidate["fooocusInpaint"] is False for candidate in result["candidates"]))
        self.assertTrue(all("Fooocus" not in node["class_type"] for call in self.workers.calls for node in call[2].values()))
        self.assertTrue(any("stronger inpainting is off" in message for message in result["warnings"]))

    async def test_exact_prepared_assets_survive_local_cleanup_and_retry_without_reselection(self):
        source = Path(self.temp.name) / "source.png"
        mask_file = Path(self.temp.name) / "mask.png"
        Image.new("RGB", (384, 512), "yellow").save(source)
        Image.new("L", (384, 512), 255).save(mask_file)
        source_asset = self.service.assets.ingest(source)
        mask_asset = self.service.assets.ingest(mask_file, "mask")
        self.llm.plan.update(mode="replace")
        self.workers.failures["w2"] = WorkerFailure("Confirmed render failure")
        body = self.body(operation="edit", sourceAssetId=source_asset["assetId"], maskAssetId=mask_asset["assetId"], editInstruction="replace the sky")
        accepted = await self.service.submit(body)
        result = await self.finished(accepted["jobId"])
        self.assertEqual(result["state"], "partial")
        manifest = result["preparedEdit"]
        self.assertEqual(manifest["metadata"]["selectionMethod"], "manual")
        self.assertEqual(set(manifest["assets"]), {"sourcePath", "maskPath", "originalPath", "finalMaskPath", "selectionMaskPath"})
        self.assertFalse(any(key.endswith("Path") for key in manifest["metadata"]))
        # Fresh runtime reads immutable masks/crops from Drive, with no working
        # files and no local cached copies required.
        for asset_id in manifest["assets"].values():
            (self.config.root / "assets" / (asset_id + ".png")).unlink(missing_ok=True)
        self.workers.failures.clear()
        with patch("router.service.prepare_edit", side_effect=AssertionError("Accepted edit preparation must never be reconstructed")):
            retried = await self.service.retry(result["jobId"], "retry-edit")
            done = await self.finished(retried["jobId"])
        self.assertEqual(done["state"], "complete")
        self.assertEqual(done["preparedEdit"], manifest)
        self.assertTrue(all(candidate["editPreparation"]["selectionMethod"] == "manual" for candidate in done["candidates"]))

    async def test_resume_reports_reserved_recipe_when_worker_capability_changes(self):
        source = Path(self.temp.name) / "source.png"
        mask_file = Path(self.temp.name) / "mask.png"
        Image.new("RGB", (384, 512), "yellow").save(source)
        Image.new("L", (384, 512), 255).save(mask_file)
        source_asset = self.service.assets.ingest(source)
        mask_asset = self.service.assets.ingest(mask_file, "mask")
        self.workers.model = "waiIllustriousSDXL_v170.safetensors"
        self.workers.capabilities = {"fooocusInpaint": True}
        self.llm.plan.update(mode="replace")
        for worker in self.config.workers:
            self.workers.gates[worker.worker_id] = asyncio.Event()
        body = self.body(operation="edit", sourceAssetId=source_asset["assetId"], maskAssetId=mask_asset["assetId"], editInstruction="replace the sky")
        body["parameters"]["model"] = self.workers.model
        accepted = await self.service.submit(body)
        for _ in range(300):
            stored = await self.service.get(accepted["jobId"])
            if all(worker.get("submissionAttempted") for worker in stored["workers"]):
                break
            await asyncio.sleep(0.01)
        self.assertTrue(all(worker["renderMetadata"]["fooocusInpaint"] for worker in stored["workers"]))
        task = self.service.tasks[accepted["jobId"]]
        task.cancel()  # Simulated router process interruption, not user cancel.
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.workers.capabilities = {}
        for gate in self.workers.gates.values():
            gate.set()
        with patch("router.service.prepare_edit", side_effect=AssertionError("Resume must use the exact saved preparation")):
            self.service.schedule(accepted["jobId"])
            result = await self.finished(accepted["jobId"])
        self.assertEqual(result["state"], "complete")
        self.assertTrue(all(candidate["fooocusInpaint"] for candidate in result["candidates"]))
        self.assertTrue(all(call[2] == {} for call in self.workers.calls[3:]))

    def download_record(self):
        return {"jobId": "download-1", "status": "running", "progress": 0, "filename": None, "error": None,
                "workers": [{"workerId": worker.worker_id, "name": worker.name, "jobId": worker.worker_id,
                             "status": "running", "progress": 0, "error": None} for worker in self.config.workers]}

    async def test_download_real_complete_payload_finishes_at_100_percent(self):
        async def reply(worker, method, path, **kwargs):
            return {"status": "complete", "progress": 100, "filename": "model.safetensors"}
        self.workers.json = reply
        self.service.journal.put_download(self.download_record())
        result = await self.service.download_status("download-1")
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["progress"], 100)
        self.assertTrue(all(worker["status"] == "complete" for worker in result["workers"]))

    async def test_download_failed_workers_are_terminal_and_partial_is_reported(self):
        async def reply(worker, method, path, **kwargs):
            return {"status": "complete", "progress": 100} if worker.worker_id == "w1" else {
                "status": "failed", "progress": 0, "error": "worker-secret private raw error"}
        self.workers.json = reply
        self.service.journal.put_download(self.download_record())
        result = await self.service.download_status("download-1")
        self.assertEqual(result["status"], "partial")
        self.assertAlmostEqual(result["progress"], 100 / 3)
        self.assertNotIn("worker-secret", str(result))
        async def should_not_poll(*args, **kwargs):
            self.fail("Terminal failed/complete workers must not be polled again")
        self.workers.json = should_not_poll
        self.assertEqual((await self.service.download_status("download-1"))["status"], "partial")
        async def failed(worker, method, path, **kwargs):
            raise WorkerFailure("Credentials were rejected.")
        self.workers.json = failed
        started = await self.service.begin_download({"kind": "checkpoint", "modelVersionId": "123", "workerId": "all"})
        self.assertEqual(started["status"], "failed")
        self.assertTrue(all(worker["status"] == "failed" for worker in started["workers"]))

    async def test_download_running_percent_is_not_clipped_to_a_fraction(self):
        async def reply(worker, method, path, **kwargs):
            return {"status": "downloading", "progress": 33}
        self.workers.json = reply
        self.service.journal.put_download(self.download_record())
        result = await self.service.download_status("download-1")
        self.assertEqual(result["status"], "running")
        self.assertEqual(result["progress"], 33)
        self.assertTrue(all(worker["progress"] == 33 for worker in result["workers"]))
