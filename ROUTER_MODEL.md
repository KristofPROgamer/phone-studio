# Router model and startup

The router uses the attached report's practical first recommendation, **Huihui-Qwen3.8-27B-abliterated**. Its publisher describes refusal reduction through abliteration and retains the visual subsystem. The implementation adds no content-moderation service. Neither the label nor the setup guarantees zero refusals, faithful reasoning or unchanged quality after quantization. [Publisher model card](https://huggingface.co/huihui-ai/Huihui-Qwen3.8-27B-abliterated).

The VLM improves prompts, plans edits and compares actual images. Image workers still generate/edit pixels with the selected SDXL checkpoint. This does not make SDXL editing equal proprietary ChatGPT/Gemini/Grok image models. Original prompts, source images, candidate settings and reviewer identities remain inspectable.

## Exact download identities

All model downloads come from `huihui-ai/Huihui-Qwen3.8-27B-abliterated-GGUF`, revision **`b146b417080fd3e0e842e9539e69921707360aae`**. The helper verifies length and SHA256 before an atomic promotion into the cache. [Pinned publisher files](https://huggingface.co/huihui-ai/Huihui-Qwen3.8-27B-abliterated-GGUF/tree/b146b417080fd3e0e842e9539e69921707360aae), [publisher metadata](https://huggingface.co/api/models/huihui-ai/Huihui-Qwen3.8-27B-abliterated-GGUF?blobs=true).

| File | Bytes | SHA256 |
| --- | ---: | --- |
| `Huihui-Qwen3.8-27B-abliterated-UD-IQ3_S.gguf` | 11,952,901,024 | `f785ad524b138cd53575410e07e93dfa6eff1cc92ca698264cb9c96973db6886` |
| `mmproj-model-bf16.gguf` | 931,145,888 | `c9a09064683620bea3d3bfed5d4462e1a97a7d2fff7e5045d6862a0a85eeb5b5` |

The repository declares Apache-2.0. The vision projector is essential; a text-only server is reported unavailable rather than being called a visual judge. This particular UD GGUF release is a publisher-modified quantization; its edited-layer range differs from the latest full Transformers checkpoint. Base-model size tables cannot identify the correct Huihui file. In particular the publisher's `Q3_K_L` is larger than a free-tier T4 target because selected tensors use higher precision. No alternate checkpoint or lower quantization is silently substituted.

The serving engine is **llama.cpp v0.5.0**, commit **`7fe450e19305b828c199d602c23a8337aaa1f03b`**, with detected CUDA architecture, including T4/SM75. The model uses the supported `qwen35` architecture. [Pinned release](https://github.com/ggml-org/llama.cpp/releases/tag/v0.5.0), [architecture source](https://raw.githubusercontent.com/ggml-org/llama.cpp/7fe450e19305b828c199d602c23a8337aaa1f03b/src/llama-arch.cpp), [CUDA build source](https://raw.githubusercontent.com/ggml-org/llama.cpp/7fe450e19305b828c199d602c23a8337aaa1f03b/ggml/src/ggml-cuda/CMakeLists.txt).

## Resource and startup choices

`PHONE_STUDIO_ROUTER_COLAB.ipynb` embeds the router and setup code. Secrets contain the three worker connections; the app saves only the router connection. Both router and LLM bind to loopback. The router port 8080 alone is tunneled, with Basic authentication and the studio token. Port 8081 and its randomly generated API key stay private. Notebook output prints the router URL; copy credentials from your Secrets, not from shared output. Source files and local logs should also remain private.

Network deployment requires independently reachable worker addresses. One ngrok Free account currently permits three concurrent agents/endpoints and one assigned development domain, so it cannot host four independent remote tunnels for these roles. A blank `NGROK_DOMAIN` uses account defaults; random URLs are not a Free-plan feature. Local private workers can use addresses reachable from the router without public tunnels. The notebook neither purchases capacity nor bypasses account limits. [Official ngrok limits](https://ngrok.com/docs/pricing-limits/free-plan-limits).

The default model cache is runtime-local, requiring approximately 12 GiB plus an 8 GiB disk reserve. Drive holds the job journal backups and assets; it does not also receive the large LLM weights. An optional existing persistent cache path can be set explicitly in the notebook. Build checks need 4 GiB available host RAM and 2 GiB scratch above the reserve; build parallelism is 2 and build timeout 30 minutes. Each download has a 40 minute maximum. Cached artifacts are hash-verified before reuse. Current Torch, torchvision and CUDA are never replaced by this helper.

One loaded LLM process uses one serial inference slot, 8K context, 256-token batches, 128-token microbatches, FP16 KV storage, automatic fitting and a 1 GiB target reserve. Dynamic image processing is capped at 1024 tokens per image. Analysis previews are resized to at most 1280 pixels per side, encoded as PNG, and used only by the local LLM; candidate originals remain intact. Structured calls disable thinking and bound output to 1400–1800 tokens. The pinned [server API](https://raw.githubusercontent.com/ggml-org/llama.cpp/7fe450e19305b828c199d602c23a8337aaa1f03b/tools/server/README.md) documents these options, vision inputs and schema output.

The native server has agent execution, web UI and MCP proxy disabled. Its child environment excludes inherited worker/router credentials and tool settings; the router sends only the bounded text/image data required for each task. The build omits unused UI, app, subprocess and OpenSSL components; public HTTPS is supplied by the router tunnel.

**Memory estimate, not a measurement:** the two files total 12.00 GiB; 8K FP16 attention KV and recurrent state add roughly 0.65 GiB, before compute buffers and driver allocations. Total usage may reach 14–15+ GiB and can fail to fit. The setup requires a separate 16 GB class or larger GPU with adequate free memory. Automatic fitting may offload layers; inspect the private server log for actual placement. T4 has no native BF16 acceleration, so a BF16-stored projector is not a promised BF16 speed benefit. Supported engine conversion/fallback handles storage types.

A failed GPU-projector startup retries once with the **same weights/projector on CPU**, prints that change, and exposes `llm.degraded=true` through health. It does not pretend to retain the same performance. If both starts fail, setup stops with a clear error. Rerunning setup reuses a verified authenticated server before applying the fresh-process free-memory check. Build/download/setup are first-start costs, not repeated per-render work.

Automatic SAM2.1 Tiny segmentation is requested on CPU by default. Its independent helper validates installed Torch/torchvision, uses pinned weights and skips an incompatible installation. Manual masks remain available. See the worker/edit documentation for exact auxiliary identities and preservation limits.

## What the adapter verifies

- Prompt enhancement requests concise Danbooru-style tags, preserving explicit counts, subjects, relationships and style. Tags are suggestions, not verified taxonomy records. User negatives stay unchanged; original text is stored separately. Invalid replies use the original prompt and visibly report enhancement unavailable.
- Edit planning receives the actual source and original instruction, returns only approved operation/strength/normalized target coordinates, and preserves user negatives. Coordinates are inputs to segmentation/manual correction; an LLM box is not labeled a precise semantic mask. Output cannot provide executable commands, models, URLs or graphs.
- Review receives the actual candidates and original request; edit review also includes the source image and instruction. Scores and winner must reference existing candidates exactly once with finite 0–10 scores. An invalid, incomplete or missing result returns review unavailable, with no invented winner. Disabled review similarly retains all unreviewed candidates.
- Calls use a 180 second cap including serial-slot waiting and obey an earlier job deadline. Cancellation propagates. Replies are bounded to 256 KiB and redirects are disabled. Timing logs contain duration and request ID, without prompt/image bodies or credentials.

This validation enforces structure and provenance, not perceptual correctness. Quantized tagging, attention to details, preservation judgment and refusal behavior still need image-based evaluation.

## Verification you can run

1. Start the router notebook: health should report the pinned revision, native vision ready and actual degraded status. Verify the router URL opens only with your credentials; port 8081 should have no public tunnel.
2. Generate a request containing a precise count and relationship. Inspect original/effective prompts, all candidate images and the review explanation; judge whether the choice actually follows the request.
3. Disable each assistant option and confirm enhancement/review labels change and every alternative remains accessible. Disconnect the local LLM and confirm review becomes unavailable without an invented selected image.
4. Upload an image, edit a manually selected small area and compare source/candidates. Confirm unselected source pixels are preserved and lineage/settings are recorded before evaluating automatic selection.
5. Send back safe GPU/runtime information, the model revision, actual placement, `[phone-studio-router-timing]`/worker timing lines and example differences. Omit Secrets, credential JSON and private source/prompt contents.

Local adapter tests use tiny raster fixtures, a mocked loopback HTTP server and synthetic replies. They do not load an LLM, compile native CUDA or measure speed. The notebook is generated from saved sources and checked for exact embedded copies; its cells are not executed here.

Four free managed Colab runtimes are not a supported availability promise. Google's current FAQ restricts distributed computing workers and remote content-generation interfaces, with variable GPU/resource limits. Use permitted/local runtimes; the code includes no account/quota bypass or paid provisioning. [Official Colab FAQ](https://research.google.com/colaboratory/faq.html).
