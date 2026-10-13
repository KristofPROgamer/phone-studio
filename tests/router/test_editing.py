import hashlib
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image

from router.editing import MaskCorrectionRequired, finish_edit, prepare_edit, _validated_targets


def source(tmp_path, size=(180, 130), alpha=False):
    rng = np.random.default_rng(5)
    pixels = rng.integers(0, 256, (*size[::-1], 4 if alpha else 3), dtype=np.uint8)
    path = tmp_path / "source.png"
    Image.fromarray(pixels, "RGBA" if alpha else "RGB").save(path)
    return path, pixels


def mask(tmp_path, size, bounds=(70, 40, 110, 85)):
    image = Image.new("L", size, 0)
    image.paste(255, bounds)
    path = tmp_path / "mask.png"
    image.save(path)
    return path, np.asarray(image)


def candidate(tmp_path, prepared, color=(255, 0, 0)):
    path = tmp_path / "candidate.png"
    Image.new("RGB", (prepared["width"], prepared["height"]), color).save(path)
    return path


@pytest.mark.parametrize("mode", ["refine", "replace"])
@pytest.mark.parametrize("alpha", [False, True])
def test_masked_stitch_exactly_preserves_unselected_pixels_and_source(tmp_path, mode, alpha):
    path, pixels = source(tmp_path, alpha=alpha)
    original_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    mask_path, selection = mask(tmp_path, (180, 130))
    prepared = prepare_edit(path, mask_path, {"mode": mode, "denoise": 0.6}, tmp_path / "work")
    with Image.open(prepared["selectionMaskPath"]) as saved_selection:
        assert np.array_equal(np.asarray(saved_selection), selection)
    result = finish_edit(prepared, candidate(tmp_path, prepared), tmp_path / "result.png")
    with Image.open(result) as image:
        actual = np.asarray(image)
    assert np.array_equal(actual[selection == 0], pixels[selection == 0])
    assert not np.array_equal(actual[selection == 255], pixels[selection == 255])
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original_hash
    assert prepared["degradedMask"] is False
    assert prepared["width"] * prepared["height"] <= 768 * 1024


def test_outpaint_preserves_original_pixels_and_expands_requested_edge(tmp_path):
    path, pixels = source(tmp_path)
    prepared = prepare_edit(path, None, {"mode": "outpaint", "denoise": 1,
        "outpaintMargins": {"right": 0.25}}, tmp_path / "work")
    result = finish_edit(prepared, candidate(tmp_path, prepared), tmp_path / "result.png")
    with Image.open(result) as image:
        actual = np.asarray(image)
    assert actual.shape == (130, 225, 3)
    assert np.array_equal(actual[:, :180], pixels)
    assert np.any(actual[:, 180:] != 127)
    assert prepared["outpaintMarginsPixels"] == {"left": 0, "top": 0, "right": 45, "bottom": 0}


def test_manual_mask_overrides_global_plan(tmp_path):
    path, _ = source(tmp_path)
    mask_path, _ = mask(tmp_path, (180, 130))
    with patch("router.editing._automatic_mask", side_effect=AssertionError("Automatic selection must not run")):
        prepared = prepare_edit(path, mask_path, {"mode": "global", "denoise": 0.4}, tmp_path / "work")
    assert prepared["mode"] == "refine"
    assert prepared["selectionMethod"] == "manual"
    assert prepared["warnings"]


def test_uncertain_automatic_selection_requests_mask_instead_of_rectangle(tmp_path, monkeypatch):
    path, _ = source(tmp_path)
    monkeypatch.delenv("PHONE_STUDIO_SAM2_CHECKPOINT", raising=False)
    with pytest.raises(MaskCorrectionRequired, match="Paint or correct"):
        prepare_edit(path, None, {"mode": "replace", "boxes": [[0.2, 0.2, 0.8, 0.8]]}, tmp_path / "work")
    assert not (tmp_path / "work" / "working-mask.png").exists()
    assert path.exists()


@pytest.mark.parametrize("bounds", [[], [[0.9, 0.2, 0.1, 0.5]], [[0, 0, 2, 1]], [[float("nan"), 0, 1, 1]]])
def test_invalid_automatic_coordinates_rejected(bounds):
    with pytest.raises(MaskCorrectionRequired):
        _validated_targets({"boxes": bounds}, (200, 100))


def test_manual_mask_wrong_dimensions_empty_and_overwrites_rejected(tmp_path):
    path, _ = source(tmp_path)
    bad = tmp_path / "bad.png"
    Image.new("L", (20, 20), 255).save(bad)
    with pytest.raises(MaskCorrectionRequired, match="dimensions"):
        prepare_edit(path, bad, {"mode": "refine"}, tmp_path / "work")
    Image.new("L", (180, 130), 0).save(bad)
    with pytest.raises(MaskCorrectionRequired, match="empty"):
        prepare_edit(path, bad, {"mode": "refine"}, tmp_path / "work")
    prepared = prepare_edit(path, None, {"mode": "global"}, tmp_path / "global")
    with pytest.raises(ValueError, match="overwrite"):
        finish_edit(prepared, candidate(tmp_path, prepared), path)


def test_global_retains_source_dimensions_and_rejects_unexpected_worker_image(tmp_path):
    path, pixels = source(tmp_path, (171, 133))
    prepared = prepare_edit(path, None, {"mode": "global", "denoise": 1}, tmp_path / "work")
    assert prepared["denoise"] == 0.95
    result = finish_edit(prepared, candidate(tmp_path, prepared), tmp_path / "result.png")
    with Image.open(result) as image:
        assert image.size == (171, 133)
    bad = tmp_path / "bad-worker.png"
    Image.new("RGB", (64, 64)).save(bad)
    with pytest.raises(ValueError, match="unexpected"):
        finish_edit(prepared, bad, tmp_path / "invalid.png")


def test_exif_rotation_normalized_before_crop(tmp_path):
    raw = Image.new("RGB", (80, 100), "blue")
    exif = Image.Exif()
    exif[274] = 6
    path = tmp_path / "rotated.jpg"
    raw.save(path, exif=exif)
    prepared = prepare_edit(path, None, {"mode": "global"}, tmp_path / "work")
    assert prepared["originalSize"] == [100, 80]
    assert prepared["normalization"]["orientationApplied"]


@pytest.mark.parametrize("mode", ["invented", "refine"])
def test_bad_modes_and_working_limits_rejected(tmp_path, mode):
    path, _ = source(tmp_path)
    with pytest.raises((ValueError, MaskCorrectionRequired)):
        prepare_edit(path, None, {"mode": mode, "workingWidth": 2048, "workingHeight": 2048}, tmp_path / "work")
