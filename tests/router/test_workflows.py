import pytest

from router.workflows import build_edit, build_generation

PARAMETERS = {"model": "waiIllustriousSDXL_v170.safetensors", "lora": "style.safetensors",
              "loraStrength": 0.7, "width": 768, "height": 1024, "preset": "balanced"}


def test_generation_two_presets_share_model_negative_and_lora_graph():
    balanced = build_generation(PARAMETERS, "1girl, green coat", "lowres", 123)
    fast = build_generation(dict(PARAMETERS, preset="fast"), "1girl, green coat", "lowres", 123)
    assert balanced["5"]["inputs"]["steps"] == 24
    assert fast["5"]["inputs"]["steps"] == 18
    assert fast["3"]["inputs"]["text"] == "lowres"
    assert fast["2"]["inputs"]["clip"] == ["8", 1]
    assert fast["8"]["inputs"]["strength_model"] == 0.7
    for graph in (balanced, fast):
        assert graph["5"]["inputs"]["cfg"] == 6.5
        assert graph["5"]["inputs"]["sampler_name"] == "dpmpp_2m"
        assert graph["5"]["inputs"]["scheduler"] == "karras"


@pytest.mark.parametrize("mode,expected", [("global", "VAEEncode"), ("refine", "SetLatentNoiseMask"),
                                            ("replace", "VAEEncodeForInpaint"), ("outpaint", "VAEEncodeForInpaint")])
def test_stock_edit_wiring_and_local_compositing(mode, expected):
    graph = build_edit(PARAMETERS, "green coat", "lowres", 22, "source.png",
                       None if mode == "global" else "mask.png", mode, 0.55)
    node = graph[graph["5"]["inputs"]["latent_image"][0]]
    assert node["class_type"] == expected
    assert graph["5"]["inputs"]["denoise"] == 0.55
    if mode != "global":
        assert graph["10"]["inputs"]["channel"] == "red"
        assert graph["17"]["inputs"]["destination"] == ["9", 0]
        assert graph["7"]["inputs"]["images"] == ["17", 0]
    assert graph["7"]["inputs"]["filename_prefix"] == "PhoneStudioEdit"
    assert not any(n["class_type"] == "EasyCache" for n in graph.values())


def test_fooocus_uses_conditioning_and_correct_dual_latent_outputs():
    graph = build_edit(PARAMETERS, "green coat", "lowres", 22, "source.png", "mask.png", "replace", 1, True)
    assert graph["15"]["inputs"]["model"] == ["8", 0]
    assert graph["15"]["inputs"]["latent"] == ["13", 2]
    sampler = graph["5"]["inputs"]
    assert sampler["model"] == ["15", 0]
    assert sampler["positive"] == ["13", 0]
    assert sampler["negative"] == ["13", 1]
    assert sampler["latent_image"] == ["13", 3]


@pytest.mark.parametrize("change", [{"model": "../escape.safetensors"}, {"preset": "lightning"},
                                     {"width": 2048, "height": 2048}, {"loraStrength": float("nan")}])
def test_approved_graph_rejects_invalid_options(change):
    with pytest.raises(ValueError):
        build_generation(dict(PARAMETERS, **change), "prompt", "negative", 1)


def test_edit_requires_mask_bounded_source_and_strength():
    for name, mask_name, mode, strength in (("source.png", None, "replace", 1),
                                           ("../source.png", "mask.png", "refine", 0.5),
                                           ("source.png", None, "global", 1),
                                           ("source.png", "mask.png", "refine", float("nan"))):
        with pytest.raises(ValueError):
            build_edit(PARAMETERS, "prompt", "negative", 1, name, mask_name, mode, strength)
