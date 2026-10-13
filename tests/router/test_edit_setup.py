"""CPU/mock checks only. No installer, model, CUDA, or notebook cell is run."""
import ast
import contextlib
import hashlib
import io
import json
import sys
import types
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image

from router.editing import MaskCorrectionRequired, _automatic_mask, SAM2_SOURCE_REVISION
from tools import edit_worker_setup as fooocus
from tools import router_segmentation_setup as segmentation

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("valid", [True, False])
def test_auxiliary_download_integrity_is_checked_atomically(tmp_path, monkeypatch, valid):
    payload = b"small fake publisher file"
    digest = hashlib.sha256(payload).hexdigest() if valid else "0" * 64
    monkeypatch.setattr(fooocus, "FOOOCUS_WEIGHTS", {"fake.patch": (len(payload), digest)})
    monkeypatch.setattr(fooocus.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(payload))
    if valid:
        fooocus._download_weight("fake.patch", tmp_path, 0)
        assert (tmp_path / "fake.patch").read_bytes() == payload
    else:
        with pytest.raises(RuntimeError, match="integrity"):
            fooocus._download_weight("fake.patch", tmp_path, 0)
        assert not (tmp_path / "fake.patch").exists()
    assert not list(tmp_path.glob("*.part"))


def test_disabled_setup_performs_no_subprocess_or_network(tmp_path):
    with patch.object(fooocus.subprocess, "run", side_effect=AssertionError("no installs")), \
         patch.object(segmentation.subprocess, "run", side_effect=AssertionError("no installs")), \
         patch.object(fooocus.urllib.request, "urlopen", side_effect=AssertionError("no downloads")):
        assert not fooocus.setup_worker_editing(tmp_path, tmp_path, enabled=False)["ready"]
        assert not segmentation.setup_segmentation(enabled=False, cache_dir=tmp_path)["ready"]


@pytest.mark.parametrize("scores,ambiguous", [([0.9, 0.75, 0.6], False), ([0.61, 0.59, 0.5], True),
                                           ([0.9, 0.88, 0.5], True)])
def test_automatic_masks_need_confidence_and_release_model_state(tmp_path, monkeypatch, scores, ambiguous):
    checkpoint = tmp_path / "fake.pt"
    checkpoint.write_bytes(b"not executed")
    monkeypatch.setenv("PHONE_STUDIO_SAM2_CHECKPOINT", str(checkpoint))
    monkeypatch.setenv("PHONE_STUDIO_SAM2_SOURCE_REVISION", SAM2_SOURCE_REVISION)
    resets, builds = [], []

    class Predictor:
        def __init__(self, model, **kwargs):
            pass

        def set_image(self, image):
            assert image.shape == (100, 120, 3)

        def predict(self, **kwargs):
            assert kwargs["box"].shape == (4,)
            masks = np.zeros((3, 100, 120), bool)
            masks[0, 20:60, 30:80] = True
            masks[1, 10:40, 10:40] = True
            masks[2, 10:30, 60:90] = True
            return masks, np.array(scores), None

        def reset_predictor(self):
            resets.append(True)

    def build(*args, **kwargs):
        builds.append(kwargs)
        return object()

    fake_modules = {"torch": types.SimpleNamespace(inference_mode=contextlib.nullcontext),
                    "sam2": types.ModuleType("sam2"),
                    "sam2.build_sam": types.SimpleNamespace(build_sam2=build),
                    "sam2.sam2_image_predictor": types.SimpleNamespace(SAM2ImagePredictor=Predictor)}
    with patch.dict(sys.modules, fake_modules):
        if ambiguous:
            with pytest.raises(MaskCorrectionRequired, match="Paint or correct"):
                _automatic_mask(Image.new("RGB", (120, 100)), {"boxes": [[0.1, 0.1, 0.9, 0.9]]})
        else:
            mask = _automatic_mask(Image.new("RGB", (120, 100)), {"boxes": [[0.1, 0.1, 0.9, 0.9]]})
            assert mask.getbbox() == (30, 20, 80, 60)
    assert resets == [True]
    assert builds[0]["device"] == "cpu"
    assert builds[0]["apply_postprocessing"] is False


def test_notebook_preserves_identity_and_embeds_current_helper_and_speed_policy():
    root = Path(__file__).resolve().parents[2]
    # tests/router → root is two parents above router directory.
    root = root.parent if not (root / "PHONE_STUDIO_COLAB.ipynb").exists() else root
    current = json.loads((root / "PHONE_STUDIO_COLAB.ipynb").read_text(encoding="utf-8"))
    previous = json.loads((root / ".work-router/original/PHONE_STUDIO_COLAB.ipynb").read_text(encoding="utf-8"))
    assert [(c.get("id"), c["cell_type"]) for c in current["cells"]] == [(c.get("id"), c["cell_type"]) for c in previous["cells"]]
    assert len(current["cells"]) == 7
    assignments = {}
    for cell in current["cells"]:
        if cell["cell_type"] != "code":
            continue
        tree = ast.parse("".join(cell["source"]))
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assignments[target.id] = node.value.value
    assert assignments["EDIT_WORKER_SETUP_CODE"].strip() == (root / "tools/edit_worker_setup.py").read_text(encoding="utf-8").strip()
    bridge = assignments["BRIDGE_CODE"]
    ast.parse(bridge)
    assert (root / "tools/speed_extras_bridge.py").read_text(encoding="utf-8").strip() in bridge
    assert "'capabilities': _phone_studio_edit_capabilities()" in bridge
    assert "if _ps_is_edit_graph(graph):" in bridge
    assert assignments["ENABLE_FOOOCUS_INPAINT"] is True


def test_worker_policy_bypasses_edits_without_changing_generation_default():
    root = Path(__file__).resolve().parents[2]
    root = root.parent if not (root / "tools/speed_extras_bridge.py").exists() else root
    tree = ast.parse((root / "tools/speed_extras_bridge.py").read_text(encoding="utf-8"))
    # Execute only these two pure Boolean functions, not the installer hooks.
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in ("_ps_is_edit_graph", "_ps_speed_requested")]
    namespace = {"_PS_COMPATIBILITY_MODE": False}
    exec(compile(ast.Module(body=functions, type_ignores=[]), "<pure-policy-test>", "exec"), namespace)
    choose = namespace["_ps_speed_requested"]
    assert choose(None, {"1": {"class_type": "EmptyLatentImage"}}) is True
    assert choose({"phone_studio_speed_extras": False}) is False
    for node in ("LoadImage", "VAEEncode", "SetLatentNoiseMask", "INPAINT_ApplyFooocusInpaint"):
        assert choose(None, {"1": {"class_type": node}}) is False
        assert choose({"phone_studio_speed_extras": True}, {"1": {"class_type": node}}) is False
    with pytest.raises(ValueError):
        choose({"phone_studio_speed_extras": "false"}, {"1": {"class_type": "LoadImage"}})
