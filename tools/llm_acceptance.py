"""Explicit real-adapter acceptance fixtures; no mocked or generated SDXL jobs.

The two smokes and optional four-image case belong to the plan's 12 cases. Inspect
semantic results against the saved expectations; valid JSON alone is insufficient.
"""
from __future__ import annotations

import asyncio
import json
import os
import runpy
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageDraw

# Direct script execution starts sys.path in tools/, whereas notebook runpy
# already has WORKSPACE. Resolve the saved source package in both entry points.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from router.llm import LLMClient, LLMUnavailable
from router.model_profile import MODEL_REPO, MODEL_REVISION
snapshot = runpy.run_path(str(Path(__file__).with_name("runtime_diagnostics.py")))["snapshot"]


def _scene(path, left="red", right="red"):
    image = Image.new("RGB", (256, 256), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((25, 35, 95, 105), fill=left)
    draw.ellipse((160, 35, 230, 105), fill=right)
    draw.rectangle((95, 155, 160, 220), fill="blue")
    image.save(path)
    image.close()


async def _measured(name, call, *, pids, expected):
    samples = []
    stopped = asyncio.Event()
    async def sample():
        while True:
            samples.append(await asyncio.to_thread(snapshot, pids=pids))
            try:
                await asyncio.wait_for(stopped.wait(), timeout=2)
                return
            except TimeoutError:
                pass
    sampler = asyncio.create_task(sample())
    started = time.monotonic()
    result = {"case": name, "expected": expected, "memory": samples,
              "memoryScope": "Observed periodic samples; not exact allocator peaks. RSS must not be summed."}
    try:
        reply = await call()
        result["output"] = reply  # Only these controlled synthetic fixtures are saved.
        result["structuredPass"] = reply.get("status") not in {"unavailable", "disabled"}
    except LLMUnavailable as error:
        result.update(structuredPass=False, error=str(error), category=getattr(error, "category", "unavailable"))
    finally:
        result["elapsedSeconds"] = round(time.monotonic() - started, 3)
        stopped.set()
        await sampler
        samples.append(await asyncio.to_thread(snapshot, pids=pids))
    return result


async def run_checks(report_path, *, four_image_only=False, pids=()):
    """Calls configured HTTP server through the same LLMClient as the application.

    Fail fast; does not reload a model or retry a failed inference. May be awaited
    directly in Colab. A nonpassing case raises after saving its private report.
    """
    client = LLMClient(os.environ.get("PHONE_STUDIO_LLM_URL", "http://127.0.0.1:8081"),
        api_key=os.environ.get("PHONE_STUDIO_LLM_API_KEY", ""),
        model_id=os.environ.get("PHONE_STUDIO_LLM_MODEL", MODEL_REPO),
        revision=os.environ.get("PHONE_STUDIO_LLM_REVISION", MODEL_REVISION))
    report = {"scope": "Actual HTTP operations through application adapter; semantic acceptance requires inspection",
              "model": client.model_id, "revision": client.revision, "cases": [], "passed": False}
    target = Path(report_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="phone-studio-llm-fixture-") as directory:
            root = Path(directory)
            source = root / "source.png"
            _scene(source)
            base = {"requestId": "acceptance-synthetic", "originalPrompt": "Two red circles above one blue square on a white background.",
                    "negativePrompt": "text, additional shapes", "options": {"enhancePrompt": True, "reviewCandidates": True}}
            if four_image_only:
                candidates, paths = [], {"source": source}
                for cid, colors in (("unchanged", ("red", "red")), ("changed-target", ("green", "red")), ("changed-both", ("green", "green"))):
                    path = root / (cid + ".png")
                    _scene(path, *colors)
                    paths[cid] = path
                    candidates.append({"candidateId": cid, "assetId": cid})
                request = {**base, "operation": "edit", "sourceAssetId": "source",
                    "editInstruction": "Make only the left red circle green. Preserve the right red circle, blue square and white background."}
                cases = [("review-source-plus-three", lambda: client.review(request, candidates, paths),
                    "Winner changed-target; complete three IDs, image-dependent explanation; preserve other shapes/background.")]
            else:
                request = {**base, "editInstruction": "Make only the left red circle green. Preserve everything else."}
                cases = [("enhancement-count-and-relationship", lambda: client.enhance(base),
                    "Two red circles ABOVE one blue square; white background; exclusions retained."),
                    ("plan-tiny-source", lambda: client.plan_edit(request, source),
                    "Local refine/replace of left circle, normalized region within left circle; other shapes/background preserved.")]
            for name, call, expected in cases:
                item = await _measured(name, call, pids=pids, expected=expected)
                # Enhancement/review return their failure status rather than
                # raising. Preserve their safe diagnostics even before INFO
                # logging is configured by the router serving process.
                item["lastInference"] = dict(client._last_inference or {})
                report["cases"].append(item)
                if not item["structuredPass"]:
                    break
            report["passed"] = len(report["cases"]) == len(cases) and all(item["structuredPass"] for item in report["cases"])
            report["qualityAccepted"] = False
            report["qualityNote"] = "Inspect outputs against expectations before claiming essential task quality."
    finally:
        await client.close()
        target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        try:
            target.chmod(0o600)
        except OSError:
            pass
    if not report["passed"]:
        raise RuntimeError(f"LLM adapter acceptance failed; inspect private report {target}. Do not reload/retry without diagnosing its category.")
    return {"structuredPass": True, "qualityAccepted": False, "report": str(target), "caseCount": len(report["cases"])}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True)
    parser.add_argument("--four-image-only", action="store_true")
    parser.add_argument("--pid", type=int, action="append", default=[])
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run_checks(args.report, four_image_only=args.four_image_only, pids=args.pid))))
