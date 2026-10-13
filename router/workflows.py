"""Approved ComfyUI graph templates; LLM output is never an executable graph."""
from __future__ import annotations

import math
from pathlib import PurePosixPath

FOOOCUS_HEAD = "fooocus_inpaint_head.pth"
FOOOCUS_PATCH = "inpaint_v26.fooocus.patch"


def _node(kind: str, **inputs) -> dict:
    return {"class_type": kind, "inputs": inputs}


def _name(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 240:
        raise ValueError(f"A valid {field} filename is required.")
    value = value.replace("\\", "/")
    path = PurePosixPath(value)
    if path.is_absolute() or ":" in value or any(p in ("", ".", "..") for p in value.split("/")):
        raise ValueError(f"The {field} filename must stay inside the worker model/input folder.")
    return value


def _base(parameters: dict, positive: str, negative: str, seed: int) -> tuple[dict, str, str, int]:
    if not isinstance(positive, str) or not positive.strip() or len(positive) > 8000:
        raise ValueError("A nonempty bounded effective prompt is required.")
    if not isinstance(negative, str) or len(negative) > 8000:
        raise ValueError("The negative prompt is too long or invalid.")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**63 - 1:
        raise ValueError("The resolved seed must be a non-negative signed 64-bit integer.")
    preset = parameters.get("preset", "balanced")
    if preset not in ("balanced", "fast"):
        raise ValueError("Choose the Balanced or Fast preset.")
    width, height = parameters.get("width", 768), parameters.get("height", 1024)
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 64 or v > 2048 or v % 8 for v in (width, height)):
        raise ValueError("Working dimensions must be multiples of 8 between 64 and 2048.")
    if width * height > 1024 * 1024:
        raise ValueError("The working canvas exceeds the supported one-megapixel SDXL budget.")
    model = _name(parameters.get("model"), "checkpoint")
    lora = parameters.get("lora", "")
    strength = parameters.get("loraStrength", 0.8)
    if isinstance(strength, bool) or not isinstance(strength, (int, float)) or not math.isfinite(strength) or not -2 <= strength <= 2:
        raise ValueError("The LoRA strength must be finite and between -2 and 2.")
    graph = {"1": _node("CheckpointLoaderSimple", ckpt_name=model)}
    model_id = clip_id = "1"
    if lora:
        graph["8"] = _node("LoraLoader", model=["1", 0], clip=["1", 1],
                           lora_name=_name(lora, "LoRA"), strength_model=strength, strength_clip=strength)
        model_id = clip_id = "8"
    graph["2"] = _node("CLIPTextEncode", text=positive, clip=[clip_id, 1])
    graph["3"] = _node("CLIPTextEncode", text=negative, clip=[clip_id, 1])
    return graph, model_id, clip_id, 24 if preset == "balanced" else 18


def _sampler(graph: dict, model_id: str, steps: int, seed: int, latent: list,
             denoise: float, positive: list | None = None, negative: list | None = None) -> None:
    graph["5"] = _node("KSampler", model=[model_id, 0], positive=positive or ["2", 0],
                       negative=negative or ["3", 0], latent_image=latent, seed=seed,
                       steps=steps, cfg=6.5, sampler_name="dpmpp_2m", scheduler="karras", denoise=denoise)
    graph["6"] = _node("VAEDecode", samples=["5", 0], vae=["1", 2])


def build_generation(parameters: dict, positive: str, negative: str, seed: int) -> dict:
    graph, model_id, _, steps = _base(parameters, positive, negative, seed)
    graph["4"] = _node("EmptyLatentImage", width=parameters.get("width", 768),
                       height=parameters.get("height", 1024), batch_size=1)
    _sampler(graph, model_id, steps, seed, ["4", 0], 1.0)
    graph["7"] = _node("SaveImage", images=["6", 0], filename_prefix="PhoneStudio")
    return graph


def build_edit(parameters: dict, positive: str, negative: str, seed: int,
               source_name: str, mask_name: str | None, mode: str,
               denoise: float, fooocus: bool = False) -> dict:
    """Caller MUST submit edits with phone_studio_speed_extras=False.

    Fooocus is selected only after an explicit worker capability check. Both
    patched and stock paths retain the selected base checkpoint and LoRA.
    """
    if mode not in ("global", "refine", "replace", "outpaint"):
        raise ValueError("Unsupported edit operation.")
    if isinstance(denoise, bool) or not isinstance(denoise, (int, float)) or not math.isfinite(denoise) or not 0.05 <= denoise <= 1:
        raise ValueError("Edit strength must be finite and between 0.05 and 1.")
    if mode == "global" and denoise >= 1:
        raise ValueError("Whole-image edits must retain some source information.")
    if mode != "global" and not mask_name:
        raise ValueError("A validated mask is required for a local edit.")
    if fooocus and mode == "global":
        raise ValueError("Fooocus inpaint needs a local or outpaint mask.")
    graph, model_id, _, steps = _base(parameters, positive, negative, seed)
    graph["9"] = _node("LoadImage", image=_name(source_name, "input image"))
    if mode == "global":
        graph["11"] = _node("VAEEncode", pixels=["9", 0], vae=["1", 2])
        latent = ["11", 0]
        positive_link, negative_link = ["2", 0], ["3", 0]
    else:
        graph["10"] = _node("LoadImageMask", image=_name(mask_name, "input mask"), channel="red")
        if fooocus:
            graph["13"] = _node("INPAINT_VAEEncodeInpaintConditioning", positive=["2", 0], negative=["3", 0],
                                pixels=["9", 0], mask=["10", 0], vae=["1", 2])
            graph["14"] = _node("INPAINT_LoadFooocusInpaint", head=FOOOCUS_HEAD, patch=FOOOCUS_PATCH)
            graph["15"] = _node("INPAINT_ApplyFooocusInpaint", model=[model_id, 0], patch=["14", 0], latent=["13", 2])
            model_id, latent = "15", ["13", 3]
            positive_link, negative_link = ["13", 0], ["13", 1]
        elif mode == "refine":
            graph["11"] = _node("VAEEncode", pixels=["9", 0], vae=["1", 2])
            graph["12"] = _node("SetLatentNoiseMask", samples=["11", 0], mask=["10", 0])
            latent = ["12", 0]
            positive_link, negative_link = ["2", 0], ["3", 0]
        else:
            graph["11"] = _node("VAEEncodeForInpaint", pixels=["9", 0], vae=["1", 2], mask=["10", 0], grow_mask_by=6)
            latent = ["11", 0]
            positive_link, negative_link = ["2", 0], ["3", 0]
    _sampler(graph, model_id, steps, seed, latent, float(denoise), positive_link, negative_link)
    # The final full-resolution stitch on the router uses the separate blend
    # mask. Preserve the unselected working pixels here as well.
    images = ["6", 0]
    if mode != "global":
        graph["17"] = _node("ImageCompositeMasked", destination=["9", 0], source=["6", 0],
                            x=0, y=0, resize_source=False, mask=["10", 0])
        images = ["17", 0]
    graph["7"] = _node("SaveImage", images=images, filename_prefix="PhoneStudioEdit")
    return graph
