"""CPU-only edit preparation/compositing; source assets are never overwritten.

Pillow/NumPy are sufficient for manual-mask edits. Torch/SAM2 are imported only
inside automatic selection, run on CPU, and released after that selection.
"""
from __future__ import annotations

import gc
import io
import math
import os
import threading
import uuid
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageFilter, ImageOps

MAX_PIXELS = 16_777_216
MAX_WORKING_PIXELS = 1_048_576
SAM2_SOURCE_REVISION = "2b90b9f5ceec907a1c18123530e92e794ad901a4"
_SEGMENT_LOCK = threading.Lock()


class MaskCorrectionRequired(ValueError):
    """Automatic selection is uncertain: keep the source and let the user paint."""
    code = "mask_correction_required"


def _manual_error(message: str) -> MaskCorrectionRequired:
    return MaskCorrectionRequired(message + " Paint or correct the area to edit, then try again. Your source is kept.")


def _atomic_png(image: Image.Image, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        image.save(temporary, format="PNG", compress_level=1)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _read_image(path: Path) -> tuple[Image.Image, dict]:
    with Image.open(path) as opened:
        if opened.width * opened.height > MAX_PIXELS or opened.width < 8 or opened.height < 8:
            raise ValueError("Source images must be at least 8×8 and no larger than 16 megapixels.")
        if getattr(opened, "n_frames", 1) != 1:
            raise ValueError("Choose a still image; animated images are not supported for editing.")
        orientation = opened.getexif().get(274, 1)
        normalized = ImageOps.exif_transpose(opened)
        has_alpha = "A" in normalized.getbands() or "transparency" in normalized.info
        normalized = normalized.convert("RGBA" if has_alpha else "RGB")
        normalization = {"sourceFormat": opened.format, "sourceMode": opened.mode,
                         "orientationApplied": orientation not in (None, 1),
                         "colorSpace": "sRGB", "alphaPreserved": has_alpha}
        profile = opened.info.get("icc_profile")
        if profile:
            try:
                from PIL import ImageCms
                source_profile = ImageCms.ImageCmsProfile(io.BytesIO(profile))
                normalized = ImageCms.profileToProfile(normalized, source_profile,
                                                      ImageCms.createProfile("sRGB"), outputMode=normalized.mode)
                normalization["colorProfileConverted"] = True
            except (OSError, ValueError, ImportError):
                # Never guess that an invalid ICC profile was converted.
                normalization["colorSpace"] = "decoded RGB; invalid profile ignored"
                normalization["colorProfileConverted"] = False
        else:
            normalization["colorProfileConverted"] = False
        return normalized.copy(), normalization


def _working_size(width: int, height: int, plan: dict) -> tuple[int, int]:
    requested_w, requested_h = plan.get("workingWidth", 768), plan.get("workingHeight", 1024)
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 64 or v > 2048 or v % 8
           for v in (requested_w, requested_h)) or requested_w * requested_h > MAX_WORKING_PIXELS:
        raise ValueError("The SDXL working canvas must fit a one-megapixel budget with dimensions divisible by 8.")
    budget = requested_w * requested_h
    scale = math.sqrt(budget / (width * height))
    # At extreme aspect ratios, cap a dimension rather than allocating a huge
    # latent. Reprojection to original dimensions is explicit in metadata.
    scale = min(scale, 2048 / width, 2048 / height)
    work_w = max(64, min(2048, int(width * scale) // 8 * 8))
    work_h = max(64, min(2048, int(height * scale) // 8 * 8))
    while work_w * work_h > budget:
        if work_w >= work_h and work_w > 64:
            work_w -= 8
        elif work_h > 64:
            work_h -= 8
        else:
            raise ValueError("The selected canvas is too small for this image.")
    return work_w, work_h


def _validated_targets(plan: dict, size: tuple[int, int]) -> tuple[list[list[float]], list[list[float]], list[int]]:
    width, height = size
    boxes = plan.get("boxes") or []
    points = plan.get("points") or []
    if not isinstance(boxes, list) or len(boxes) > 8 or not isinstance(points, list) or len(points) > 16:
        raise _manual_error("The suggested selection is invalid.")
    pixel_boxes, pixel_points, labels = [], [], []
    for box in boxes:
        if isinstance(box, dict):
            box = [box.get(k) for k in ("x0", "y0", "x1", "y1")]
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            raise _manual_error("The suggested selection has invalid coordinates.")
        if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) or not 0 <= v <= 1 for v in box):
            raise _manual_error("The suggested selection is outside the image.")
        x0, y0, x1, y1 = box
        if x0 >= x1 or y0 >= y1:
            raise _manual_error("The suggested selection has no area.")
        pixel_boxes.append([x0 * (width - 1), y0 * (height - 1), x1 * (width - 1), y1 * (height - 1)])
    for point in points:
        if isinstance(point, dict):
            point = [point.get("x"), point.get("y"), point.get("label", 1)]
        if not isinstance(point, (list, tuple)) or len(point) not in (2, 3):
            raise _manual_error("The suggested selection has invalid points.")
        x, y = point[:2]
        label = point[2] if len(point) == 3 else 1
        if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) or not 0 <= v <= 1 for v in (x, y)) or label not in (0, 1):
            raise _manual_error("The suggested selection has invalid points.")
        pixel_points.append([x * (width - 1), y * (height - 1)])
        labels.append(int(label))
    if not pixel_boxes and (not pixel_points or 1 not in labels):
        raise _manual_error("The assistant could not identify a specific edit area.")
    return pixel_boxes, pixel_points, labels


def _mask_iou(a: np.ndarray, b: np.ndarray) -> float:
    union = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / union) if union else 0.0


def _automatic_mask(image: Image.Image, plan: dict) -> Image.Image:
    boxes, points, labels = _validated_targets(plan, image.size)
    checkpoint = os.environ.get("PHONE_STUDIO_SAM2_CHECKPOINT", "")
    config = os.environ.get("PHONE_STUDIO_SAM2_CONFIG", "configs/sam2.1/sam2.1_hiera_t.yaml")
    if not checkpoint or not Path(checkpoint).is_file() or os.environ.get("PHONE_STUDIO_SAM2_SOURCE_REVISION") != SAM2_SOURCE_REVISION:
        raise _manual_error("Automatic selection is unavailable on this router.")
    # SAM's Hydra setup and CPU inference are serialized and temporary. Do not
    # retain a second model beside the persistent language/vision model.
    predictor = model = None
    with _SEGMENT_LOCK:
        try:
            import torch
            from sam2.build_sam import build_sam2
            from sam2.sam2_image_predictor import SAM2ImagePredictor
            model = build_sam2(config, checkpoint, device="cpu", apply_postprocessing=False)
            predictor = SAM2ImagePredictor(model, max_hole_area=0, max_sprinkle_area=0)
            with torch.inference_mode():
                predictor.set_image(np.asarray(image.convert("RGB"), dtype=np.uint8))
                selected = np.zeros((image.height, image.width), dtype=bool)
                for box in boxes or [None]:
                    masks, scores, _ = predictor.predict(
                        point_coords=np.asarray(points, dtype=np.float32) if points else None,
                        point_labels=np.asarray(labels, dtype=np.int32) if points else None,
                        box=np.asarray(box, dtype=np.float32) if box else None,
                        multimask_output=True, return_logits=False, normalize_coords=True)
                    masks = np.asarray(masks, dtype=bool)
                    scores = np.asarray(scores, dtype=np.float32).reshape(-1)
                    if masks.ndim != 3 or masks.shape[1:] != selected.shape or not len(scores) or len(scores) != len(masks) or not np.isfinite(scores).all():
                        raise _manual_error("Automatic selection returned an invalid mask.")
                    order = np.argsort(scores)[::-1]
                    best = int(order[0])
                    if scores[best] < 0.70:
                        raise _manual_error("Automatic selection is not confident about the target.")
                    if len(order) > 1 and scores[best] - scores[order[1]] < 0.04 and _mask_iou(masks[best], masks[order[1]]) < 0.70:
                        raise _manual_error("Automatic selection found several different possible regions.")
                    area = int(masks[best].sum())
                    if area < 12 or area > selected.size * 0.95:
                        raise _manual_error("Automatic selection could not isolate the target.")
                    selected |= masks[best]
            return Image.fromarray(selected.astype(np.uint8) * 255, mode="L")
        except MaskCorrectionRequired:
            raise
        except Exception as error:
            # No private paths, tracebacks or backend details in user errors.
            raise _manual_error("Automatic selection could not finish on this router.") from error
        finally:
            if predictor is not None:
                try:
                    predictor.reset_predictor()
                except Exception:
                    pass  # Cleanup must not hide the useful manual-correction error.
            predictor = model = None
            gc.collect()


def _manual_mask(path: Path, size: tuple[int, int]) -> Image.Image:
    with Image.open(path) as opened:
        if opened.size != size:
            raise _manual_error("The uploaded mask does not match the source dimensions.")
        if getattr(opened, "n_frames", 1) != 1:
            raise _manual_error("The uploaded mask must be a still image.")
        mask = opened.convert("L").point(lambda v: 255 if v >= 128 else 0)
    if mask.getbbox() is None:
        raise _manual_error("The edit selection is empty.")
    return mask


def _expanded_canvas(source: Image.Image, plan: dict) -> tuple[Image.Image, Image.Image, dict]:
    fractions = plan.get("outpaintMargins")
    if fractions is None:
        fractions = {side: 0.25 for side in ("left", "top", "right", "bottom")}
    if not isinstance(fractions, dict) or any(side not in ("left", "top", "right", "bottom") for side in fractions):
        raise ValueError("Outpaint margins are invalid.")
    pixels = {}
    for side in ("left", "top", "right", "bottom"):
        value = fractions.get(side, 0)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("Outpaint expansion must be between 0 and 100% per side.")
        pixels[side] = int(round(value * (source.width if side in ("left", "right") else source.height)))
    if not any(pixels.values()):
        raise ValueError("Outpainting needs at least one expanded edge.")
    size = (source.width + pixels["left"] + pixels["right"], source.height + pixels["top"] + pixels["bottom"])
    if size[0] * size[1] > MAX_PIXELS:
        raise ValueError("The expanded canvas would exceed 16 megapixels; use a smaller source or expansion.")
    canvas = Image.new(source.mode, size, (127, 127, 127, 255) if source.mode == "RGBA" else (127, 127, 127))
    canvas.paste(source, (pixels["left"], pixels["top"]))
    mask = Image.new("L", size, 255)
    mask.paste(0, (pixels["left"], pixels["top"], pixels["left"] + source.width, pixels["top"] + source.height))
    return canvas, mask, pixels


def prepare_edit(source_path: Path, mask_path: Path | None, plan: dict, work_dir: Path) -> dict:
    source_path, work_dir = Path(source_path).resolve(), Path(work_dir).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    reserved = [work_dir / name for name in ("normalized-source.png", "working-source.png", "working-mask.png", "blend-mask.png", "selection-mask.png")]
    if source_path in reserved or (mask_path and Path(mask_path).resolve() in reserved):
        raise ValueError("Edit working files must be separate from source assets.")
    mode = plan.get("mode")
    if mode not in ("global", "refine", "replace", "outpaint"):
        raise ValueError("The assistant returned an unsupported edit operation.")
    denoise = plan.get("denoise", 0.45 if mode in ("global", "refine") else 1.0)
    if isinstance(denoise, bool) or not isinstance(denoise, (int, float)) or not math.isfinite(denoise) or not 0.05 <= denoise <= 1:
        raise ValueError("The assistant returned an invalid edit strength.")
    if mode == "global":
        denoise = min(0.95, denoise)
    source, normalization = _read_image(source_path)
    source_size = source.size
    warnings = []
    if normalization["colorSpace"] != "sRGB":
        warnings.append("The source color profile could not be converted; decoded colors are retained.")
    if mask_path and mode == "global":
        mode = "refine"
        warnings.append("The painted selection limits this edit to the selected area.")
    expansion = None
    selection_method = "none"
    if mode == "outpaint":
        if mask_path:
            raise ValueError("Clear the painted selection before expanding the canvas, or choose a local edit.")
        source, mask, expansion = _expanded_canvas(source, plan)
        selection_method = "new canvas edges"
    elif mode != "global":
        mask = _manual_mask(Path(mask_path), source.size) if mask_path else _automatic_mask(source, plan)
        selection_method = "manual" if mask_path else "SAM2.1 Tiny CPU"
    else:
        mask = None
    # Preserve the normalized source before any crop/resizing. Outpaint stores
    # an expanded base canvas separately from the immutable uploaded asset.
    original_path, working_path, working_mask_path, blend_path, selection_path = reserved
    _atomic_png(source, original_path)
    if mask is None or mode == "outpaint":
        box = (0, 0, source.width, source.height)
    else:
        bounds = mask.getbbox()
        if bounds is None:
            raise _manual_error("The edit selection is empty.")
        padding = max(32, round(max(bounds[2] - bounds[0], bounds[3] - bounds[1]) * 0.25))
        x0, y0 = max(0, bounds[0] - padding), max(0, bounds[1] - padding)
        x1, y1 = min(source.width, bounds[2] + padding), min(source.height, bounds[3] + padding)
        box = (x0, y0, x1 - x0, y1 - y0)
    x, y, crop_w, crop_h = box
    crop_bounds = (x, y, x + crop_w, y + crop_h)
    work_size = _working_size(crop_w, crop_h, plan)
    working = source.crop(crop_bounds).resize(work_size, Image.Resampling.LANCZOS)
    # Comfy takes RGB for the diffusion VAE. Alpha is retained in the full
    # normalized original and final unselected pixels.
    if working.mode == "RGBA":
        flattened = Image.new("RGB", work_size, (255, 255, 255))
        flattened.paste(working, mask=working.getchannel("A"))
        working = flattened
    _atomic_png(working, working_path)
    final_mask_path = None
    if mask is not None:
        _atomic_png(mask, selection_path)
        resized = mask.crop(crop_bounds).resize(work_size, Image.Resampling.NEAREST)
        _atomic_png(resized, working_mask_path)
        # Feather inward for local edits: zero-valued pixels outside the user's
        # selection stay exactly unchanged. Outpainting preserves the original
        # canvas and uses a hard stitch; source pixels cannot fade away.
        blend = mask if mode == "outpaint" else ImageChops.multiply(mask, mask.filter(ImageFilter.GaussianBlur(2)))
        _atomic_png(blend, blend_path)
        final_mask_path = str(blend_path)
    return {"sourcePath": str(working_path), "maskPath": str(working_mask_path) if mask is not None else None,
            "originalPath": str(original_path), "uploadedSourcePath": str(source_path),
            "finalMaskPath": final_mask_path, "selectionMaskPath": str(selection_path) if mask is not None else None,
            "box": list(box), "originalSize": list(source.size),
            "sourceSize": list(source_size), "width": work_size[0], "height": work_size[1],
            "mode": mode, "denoise": float(denoise), "normalization": normalization,
            "outpaintMarginsPixels": expansion, "selectionMethod": selection_method,
            "degradedMask": False, "warnings": warnings,
            "segmentationRevision": SAM2_SOURCE_REVISION if selection_method == "SAM2.1 Tiny CPU" else None}


def finish_edit(prepared: dict, candidate_path: Path, output_path: Path) -> Path:
    candidate_path, output_path = Path(candidate_path).resolve(), Path(output_path).resolve()
    original_path = Path(prepared["originalPath"]).resolve()
    protected = {original_path, Path(prepared["sourcePath"]).resolve()}
    if prepared.get("uploadedSourcePath"):
        protected.add(Path(prepared["uploadedSourcePath"]).resolve())
    if output_path in protected or output_path == candidate_path:
        raise ValueError("An edit result must not overwrite a source or worker candidate.")
    with Image.open(original_path) as opened:
        original = opened.copy()
    with Image.open(candidate_path) as opened:
        if opened.size != (prepared["width"], prepared["height"]):
            raise ValueError("The worker returned an image with unexpected edit dimensions.")
        if getattr(opened, "n_frames", 1) != 1:
            raise ValueError("The worker edit result must be a still image.")
        candidate = opened.convert(original.mode)
    if list(original.size) != prepared["originalSize"]:
        raise ValueError("The normalized edit source changed while rendering.")
    x, y, width, height = prepared["box"]
    if any(isinstance(v, bool) or not isinstance(v, int) for v in (x, y, width, height)) or x < 0 or y < 0 or width < 1 or height < 1 or x + width > original.width or y + height > original.height:
        raise ValueError("The edit crop is outside the original canvas.")
    resized = candidate.resize((width, height), Image.Resampling.LANCZOS)
    if prepared["mode"] == "global":
        output = resized
    else:
        mask_path = prepared.get("finalMaskPath")
        if not mask_path:
            raise ValueError("The final edit mask is missing.")
        with Image.open(mask_path) as opened:
            if opened.size != original.size:
                raise ValueError("The final edit mask dimensions changed.")
            mask = opened.convert("L").crop((x, y, x + width, y + height))
        output = original.copy()
        output.paste(resized, (x, y), mask)
    _atomic_png(output, output_path)
    return output_path
