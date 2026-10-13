"""The two audited assistant pairs; selection is explicit and never automatic."""
from __future__ import annotations

PRIMARY_PROFILE = {
    "name": "4b", "repository": "mradermacher/Huihui-Qwen3.5-4B-abliterated-GGUF",
    "revision": "4a5daa6fbefca5fe822dc65fcb95cc4576fa9720", "architecture": "qwen35",
    "baseModel": "huihui-ai/Huihui-Qwen3.5-4B-abliterated", "originalBaseModel": "Qwen/Qwen3.5-4B",
    "publisher": "huihui-ai", "quantizer": "mradermacher", "license": "apache-2.0",
    "licenseSource": "https://huggingface.co/Qwen/Qwen3.5-4B/blob/main/LICENSE",
    "artifacts": (
        {"name": "Huihui-Qwen3.5-4B-abliterated.Q4_K_M.gguf", "size": 2707514688,
         "sha256": "423f10b6ec2d99c3378143d7cd3b80eb4887b3ed92103103ac59173b404f4f7c"},
        {"name": "Huihui-Qwen3.5-4B-abliterated.mmproj-f16.gguf", "size": 672423552,
         "sha256": "f14643c11f1e8244c59bca670e2a4c843be4234aa6bb88d0647dae7297798686"},
    ),
}
QUALITY_FALLBACK_PROFILE = {
    "name": "9b", "repository": "mradermacher/Huihui-Qwen3.5-9B-abliterated-GGUF",
    "revision": "9f646d7eda193ddf2348134f3bff3d49eed7a2c6", "architecture": "qwen35",
    "baseModel": "huihui-ai/Huihui-Qwen3.5-9B-abliterated", "originalBaseModel": "Qwen/Qwen3.5-9B",
    "publisher": "huihui-ai", "quantizer": "mradermacher", "license": "apache-2.0",
    "licenseSource": "https://huggingface.co/Qwen/Qwen3.5-9B/blob/main/LICENSE",
    "artifacts": (
        {"name": "Huihui-Qwen3.5-9B-abliterated.Q4_K_M.gguf", "size": 5627045248,
         "sha256": "ea1858ef4dc4b648b8dbb44612962a0333e945060dd0545ac0f28d7c4416e4b3"},
        {"name": "Huihui-Qwen3.5-9B-abliterated.mmproj-f16.gguf", "size": 918166016,
         "sha256": "56f07ff42fc9ab24fc06a93dce5a48fb2dbe08bff1a1c6e519d50af450820148"},
    ),
}
MODEL_REPO = PRIMARY_PROFILE["repository"]
MODEL_REVISION = PRIMARY_PROFILE["revision"]
ARTIFACTS = PRIMARY_PROFILE["artifacts"]

# Kept as one serving policy so reuse cannot accept changed context/placement flags.
SERVER_SETTINGS = {
    "context": 8192, "parallel": 1, "batch": 256, "microbatch": 128,
    "fit": "on", "fitTargetMiB": 1024, "flashAttention": "auto",
    "cacheK": "f16", "cacheV": "f16", "imageMinTokens": 256,
    "imageMaxTokens": 1024, "mtmdBatchMaxTokens": 1024, "thinking": False,
    "cacheRamMiB": 0,
}


def get_profile(name: str = "4b", *, quality_fallback_confirmed: bool = False) -> dict:
    if name == "4b":
        return PRIMARY_PROFILE
    if name == "9b" and quality_fallback_confirmed is True:
        return QUALITY_FALLBACK_PROFILE
    if name == "9b":
        raise ValueError("The 9B pair is only for demonstrated essential 4B quality failure after one targeted correction; explicitly confirm that gate.")
    raise ValueError("Use the audited 4b profile or its single conditional 9b quality fallback.")
