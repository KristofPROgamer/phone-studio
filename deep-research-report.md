# Best Free Uncensored Open-Weight LLMs at the End of September 2026

## Bottom line

After checking the current model cards, quantizations, model-family documentation, independent leaderboards, and recent research on refusal removal, **your main recommendation is directionally correct, but the framing needs tightening**.

For someone who wants a model that is **actually runnable on one consumer GPU, broadly capable at reasoning/coding/agents, multimodal, long-context, and substantially less refusal-prone than the original checkpoint**, **Huihui-Qwen3.8-27B-abliterated is probably the strongest default recommendation right now**. Qwen3.8-27B is a 27B-class dense model—Hugging Face reports roughly 28B parameters in the checkpoint metadata—with native image understanding, a 262,144-token context window extensible to 1M, Apache 2.0 licensing, and extremely strong coding/agent benchmarks for its size. citeturn18view0turn17view0turn18view5turn18view1

But I would **not** call it the absolute “best open-weight LLM.” On Artificial Analysis's current open-weight ranking, **MiMo-V2.6-Pro is #1 with an Intelligence Index of 46, GLM-5.3 Max is #2 at 45, and Kimi K3 Max is #3 at 44**. Qwen3.8-27B is substantially smaller and therefore much more relevant to ordinary local users, but it does not lead the unrestricted hardware category. citeturn15view9turn9search9

So the strongest defensible version of your claim is:

> **Best practical uncensored general-purpose model for a single high-end consumer GPU:** Huihui-Qwen3.8-27B-abliterated, especially around Q4–Q5.

That distinction—**best practical local model rather than best raw open-weight model**—is important.

My revised late-September/October 1, 2026 shortlist is:

| Category | Best choice | Assessment |
|---|---|---|
| **Best overall for one 24–32GB GPU** | **Huihui-Qwen3.8-27B-abliterated** | ★★★★★ |
| **Best raw open-weight intelligence, hardware no object** | **MiMo-V2.6-Pro** | ★★★★★ |
| **Best giant agent/coding alternative** | **GLM-5.3 / GLM-5.3-Flash** | ★★★★★ |
| **Best efficient MoE** | **Gemma 4 26B-A4B uncensored/abliterated** | ★★★★½ |
| **Best “uncensored by training philosophy”** | **Hermes 4 family** | ★★★★½ |
| **Best mature lightweight uncensored chat model** | **Dolphin 3.0 Mistral 24B** | ★★★½ |
| **Best fallback to Qwen3.8** | **Qwen3.6-27B abliterated** | ★★★★ |
| **Best dedicated RP/ERP** | Specialized finetunes, highly subjective | Separate category |

The key reason Qwen3.8-27B wins the *practical* category is unusually good capability per stored parameter. Its official evaluations report **61.7 on SWE-bench Pro, 73.0 on Terminal Bench 2.1, 90.3 on LiveCodeBench v6, 89.2 on GPQA Diamond, 79.5 on IFBench, and 70.7 on CoWorkBench**. Qwen's own comparisons also show a substantial generational jump over Qwen3.6-27B, especially on software engineering and agentic tasks. These are manufacturer-run results, so they should not be treated as neutral rankings, but the magnitude of the improvement is meaningful. citeturn18view1turn18view2

Independent rankings reinforce the broader point that Qwen3.8-27B is unusually competitive for a consumer-sized checkpoint. At the same time, the independent results are precisely why I would remove phrases such as “current king of open weights”: the absolute open-weight leaders are much larger systems. citeturn15view9turn9search1

## What your original draft gets right — and what I would correct

### Qwen3.8-27B really is the standout consumer-sized base

This part of your draft holds up very well.

Qwen3.8-27B is **not merely a text model with a separate vision variant**. The standard `Qwen/Qwen3.8-27B` checkpoint itself accepts image and text input through the multimodal model interface. Its official architecture specifies 24 query attention heads, four KV heads, native 262K context, and an extension path to 1M tokens. citeturn16view0turn17view0

Its multimodal results are also much more serious than “multimodal support on some variants” implies. Qwen reports **84.3 on OSWorld-Verified, 64.8 on WebArena-Verified, 81.9 on AndroidWorld, and 38.6 on SWE-MM** for Qwen3.8-27B. Again, those numbers come from the developer's own evaluation suite, but they demonstrate that vision/computer-use capability is part of the actual model design rather than a bolt-on novelty. citeturn18view2turn18view4

The license claim is also correct for the original checkpoint: **Qwen3.8-27B is Apache 2.0**. citeturn18view5

### The Huihui checkpoint is genuinely an abliteration, but “quality fully preserved” is too strong

`huihui-ai/Huihui-Qwen3.8-27B-abliterated` is real and actively maintained. The current model card says the latest revision selectively ablates **layers 18 through 51**, while leaving the other layers, the MTP component, and the visual subsystem untouched. Huihui says this narrower intervention is intended to retain more of the original model's performance. citeturn17view3

That gives the Huihui build a reasonable technical argument for being the default uncensored Qwen3.8 checkpoint. However, I would change:

> “strip refusals very effectively while keeping quality high”

to something more defensible:

> “aggressively reduces refusal behavior while attempting to preserve the base model's capabilities; the degree of behavioral preservation remains checkpoint- and task-dependent.”

The reason is that **abliteration is not guaranteed to be behaviorally surgical**. A 2026 study comparing abliterated and original Qwen/Gemma-family checkpoints found statistically measurable changes outside refusal behavior. Abliterated Qwen models in that experiment became more optimistic in decisions, expressed greater confidence, used fewer explicit uncertainty markers, and changed their decision horizon. The authors' central conclusion is that an abliterated checkpoint should not be treated as simply “the original model minus refusals.” citeturn15view11

That does **not** mean the Huihui Qwen3.8 checkpoint is bad. It means the honest recommendation is “extremely attractive for low-refusal local use, but benchmark it against the unmodified Qwen checkpoint for tasks where calibration and agent behavior matter.”

### The VRAM statement needs two important corrections

Your Q4/Q5 intuition is basically right, but “comfortably on a single 24GB GPU” is a little optimistic.

Current Qwen3.8-27B GGUF builds from Unsloth are approximately:

| Quant | Weight-file size | Practical interpretation |
|---|---:|---|
| IQ3 / Q3 | **10.9–13.1GB** | Easy 16GB fit, but substantial quantization |
| IQ4_XS | **14.3GB** | Best candidate for a 16GB GPU |
| Q4_K_S | **15.4GB** | Borderline 16GB once runtime overhead is included |
| Q4_K_M | **16.5GB** | Excellent 24GB target |
| Q4_K_XL | **17.6GB** | Still sensible on 24GB |
| Q5_K_S | **18.7GB** | Good 24GB candidate at moderate context |
| Q5_K_M | **19.8GB** | Fits weights; runtime headroom becomes important |
| Q5_K_XL | **20.9GB** | Tight on 24GB |
| Q6_K | **22.0GB** | Too close to 24GB for carefree full-GPU operation |
| Q6_K_M | **23.1GB** | Weight fit ≠ usable VRAM fit |
| Q8_0 | **29GB** | 32GB-class territory |
| BF16 | **54.7GB** | Multi-GPU / large unified-memory territory |

Those are actual current quant file sizes, not theoretical “0.5 byte per parameter” estimates. citeturn16view3

A model file taking 20GB does **not** mean a 24GB GPU has 4GB of freely usable context. Inference also needs working memory and a KV cache, and Qwen3.8's very large native 262K window makes context allocation especially relevant. Consequently, **Q4_K_M is the sensible sweet spot for a 24GB card**, while Q5 can work but becomes increasingly constrained as context grows. The advertised 262K native context should absolutely not be interpreted as “you can use all 262K comfortably with Q5 on a 24GB 4090.” Qwen confirms the native 262,144-token window, but hardware feasibility remains a separate issue. citeturn17view0turn16view3

There is also a small hardware error in the original text: **RTX 3090 and RTX 4090 are 24GB cards, but RTX 5090 is a 32GB GDDR7 card**. NVIDIA's own specifications list the RTX 4090 at 24GB and the RTX 5090 at 32GB. citeturn20search4turn21search0

That actually makes Qwen3.8 substantially nicer on a 5090 than your draft implies: with 32GB, Q6 becomes straightforward and even the 29GB Q8_0 weights become possible, though Q8 still leaves limited headroom for long context. citeturn16view3turn21search0

### “Squeezed into 16GB” is true, with qualifications

The 14.3GB IQ4_XS version genuinely fits inside a nominal 16GB footprint at the weight-file level, and several Q3 choices give much more room. But a 16GB card should be described as **“possible with aggressive quantization and constrained context,” not equivalent to the 24GB experience**. citeturn16view3

So I would rewrite your hardware line as:

> **16GB:** IQ4/Q3 territory; practical for ordinary conversations and smaller context windows.  
> **24GB:** Q4 is the sweet spot; some Q5 configurations work well.  
> **32GB:** Q5/Q6 comfortably; Q8 becomes possible.  
> **48GB+:** high precision and/or much more context headroom.

## How the individual contenders actually compare

### Qwen3.8-27B abliterated — strongest overall practical recommendation

**Verdict: keep it at #1 for the “normal enthusiast hardware” category.**

What makes Qwen3.8 distinctive is that it is strong simultaneously at general reasoning, coding, agentic work, instruction following, vision, and long context. Qwen reports the aforementioned 61.7 SWE-bench Pro and 90.3 LiveCodeBench v6, while its computer-use and browser-use evaluations are also considerably above Qwen3.6-27B. citeturn18view1turn18view2

The base checkpoint is Apache 2.0 and has broad current serving support. Its Hugging Face page documents vLLM and SGLang deployment, while quantized versions are already available for the broader local-inference ecosystem. citeturn18view5turn16view1turn16view3

Huihui's abliteration preserves the visual subsystem rather than producing a text-only derivative, which is especially useful because multimodality is one of Qwen3.8's real advantages over many older “uncensored” finetunes. citeturn17view3turn18view4

**My rating:** **9.5/10 as a 24–32GB local all-rounder.**

The main caveat is that I would test the unmodified model and abliterated checkpoint side-by-side before deploying the latter as a high-stakes autonomous agent. Recent abliteration research gives good reason not to assume identical calibration and decision behavior. citeturn15view11

### Gemma 4 26B-A4B — more important than your draft makes it sound

**Verdict: arguably the most interesting alternative to Qwen3.8 when speed matters.**

Google's Gemma 4 26B-A4B is a **25.2B-total-parameter MoE with only 3.8B active parameters per token**, using eight active experts out of 128 plus a shared expert. It supports text and image input and a 256K context window. Google explicitly describes the architecture as running much faster than its 26B total size would suggest. citeturn17view4turn17view5

This distinction is critical:

**3.8B active does not mean it occupies the memory of a 3.8B model.**

The full expert weights still have to exist somewhere in GPU or system memory. What the MoE arrangement primarily reduces is **compute per generated token**, not the amount of model data that must be stored. That makes Gemma 4 unusually fast for its quality while keeping its quantized storage footprint in roughly the same broad class as other mid-20B models. citeturn17view4

Google reports **82.6 MMLU-Pro, 88.3 AIME 2026, 77.1 LiveCodeBench v6, and 82.3 GPQA Diamond** for the 26B-A4B model. Those are not as strong overall as Qwen3.8's headline coding/reasoning results, but the much lower active parameter count makes Gemma attractive when tokens-per-second matters more than absolute maximum capability. citeturn17view5

Gemma 4 is also now **Apache 2.0**, which makes the licensing situation much cleaner than some previous generations of open-weight models. citeturn18view6

Huihui and other community developers have produced uncensored/abliterated Gemma derivatives. Your mention of “Heretic” variants is therefore reasonable, although **“Gemma 4 uncensored” is an ecosystem of modified checkpoints rather than one canonical model with one standardized benchmark result**. citeturn19search2turn14search5

**My rating:** **9/10 for efficiency-focused local use.**

I would rank it above Dolphin 3.0 in a 2026 general-purpose list.

### Hermes 4 — better described as steerable than “abliterated”

**Verdict: your conceptual description is right and is one of the strongest parts of the original list.**

Hermes 4 is important because it represents a fundamentally different approach. Rather than taking an aligned model and editing away a refusal direction afterward, Nous Research explicitly post-trained Hermes to be **broadly neutral, user-steerable, capable of reasoning/tool use, and less refusal-prone**. The Hermes 4 70B card describes approximately **5 million training samples / 60 billion post-training tokens**, hybrid reasoning, schema/JSON training, and large improvements in steerability and refusal rates. citeturn17view7turn18view7

Nous also created **RefusalBench** to measure willingness to comply with requests that other models commonly reject, and says Hermes 4 achieved its best results on that benchmark. Because Nous designed both the model and the benchmark, I would treat this as supporting evidence rather than an independent proof of superiority, but it makes the design philosophy very explicit. citeturn17view6

The 70B model is based on **Llama 3.1 70B**, while a practical **Hermes 4 14B** model also exists in the official Nous repository. The Nous organization additionally has a Hermes 4.3 36B checkpoint and a 405B Hermes 4 release, so “Hermes 4” should really be treated as a family rather than one hardware tier. citeturn18view7turn19search16

One correction to the broad “all Apache 2.0” implication: **Hermes 4 licensing depends on the underlying model**. The 14B Qwen-based model and 70B Llama-based model do not necessarily carry identical base-model licensing. The 70B model explicitly derives from Meta's Llama 3.1 70B. citeturn18view7turn12search2

**My rating:** **8.5/10 overall, 9.5/10 specifically for controllability/steerability.**

For someone who dislikes the conceptual messiness of abliteration and wants a model intentionally trained to respond according to the owner's system prompt, Hermes remains one of the most defensible recommendations.

### Dolphin 3.0 Mistral 24B — still good, but no longer #2

**Verdict: move it down the ranking.**

Dolphin 3.0 Mistral 24B remains a genuinely useful uncensored local model. Its own card describes the design goal as letting the system owner control the model's alignment rather than imposing Dolphin's own ethics, and it was specifically trained for general chat, coding, math, agents, and function calling. citeturn16view10

The checkpoint is based on **Mistral Small 24B Base 2501** and has abundant quantizations. Its model card even provides an Ollama configuration around **13GB**, making it easy to run on ordinary consumer hardware. citeturn18view9turn17view8

The problem with putting it at #2 in late 2026 is simply technological age. The current Qwen3.8 and Gemma 4 generation has moved substantially beyond the 2025-era Mistral Small base in reasoning, multimodality, context, and agentic capability. Qwen3.8's official results in particular are in a different capability class. citeturn18view1turn17view5

That does **not** invalidate Dolphin. It changes the reason to select it.

Choose Dolphin today because you want:

**mature behavior + simple deployment + strong system-prompt steerability + comparatively low hardware requirements**, not because it is the second-smartest open model available. citeturn16view10turn17view8

**My rating:** **7.5/10 as a current general model, 8.5/10 as a mature uncensored conversational model.**

### Qwen3.6-27B abliterated — still solid, but mostly a compatibility fallback

Qwen3.6-27B remains available and well-supported, but Qwen's own controlled comparisons now give very little capability-based reason to prefer it to 3.8. For example, Qwen reports the jump from Qwen3.6-27B to Qwen3.8-27B as **63.4 → 73.0 on Terminal Bench 2.1, 53.5 → 61.7 on SWE-bench Pro, 13.3 → 42.2 on DeepSWE 1.1, 49.3 → 79.0 on QwenSWEBench, and 83.9 → 90.3 on LiveCodeBench v6**. citeturn18view1

So I would retain 3.6 only when a particular quantization, backend, finetune, or established workflow behaves better on your hardware.

**My rating:** **8/10, but largely superseded by 3.8.**

### MiMo-V2.6-Pro — the actual raw open-weight leader, but not a consumer model

This needs much more prominence in your “larger / higher-end” section.

Xiaomi's official Hugging Face organization lists **MiMo-V2.6-Pro-RL as a 1-trillion-parameter model**. It also offers a 311B V2.6 Flash model and a much smaller 9B Qwen-based distillation. citeturn15view8

Independent Artificial Analysis currently identifies **MiMo-V2.6-Pro as the highest-ranked open-weight model**, at an Intelligence Index of 46. That makes your claim that it “frequently ranks at or near the top” not just plausible but currently conservative: on that benchmark suite, it is literally #1 among open weights as of this research. citeturn15view9

The obvious catch is the **1T parameter footprint**. Even when sparsity means only a subset of parameters participates in each token, all those expert weights still need storage or offloading. It belongs to a fundamentally different deployment category from a Qwen 27B GGUF. citeturn15view8

So the right distinction is:

**MiMo-V2.6-Pro = best open-weight intelligence contender.**  
**Qwen3.8-27B abliterated = much better answer to “what should I download for my gaming PC?”**

### GLM-5.3 — extremely capable, extremely not 24GB-local

The current GLM lineup deserves essentially the same treatment.

Z.ai's official repository lists:

- **GLM-5.3: 744B total / 40B active**
- **GLM-5.3-Flash: 320B total / 18B active**

with FP8 and BF16 releases. Official local-serving support includes SGLang, vLLM, Transformers, KTransformers, Unsloth, and additional frameworks depending on the variant. citeturn17view9turn17view10

Artificial Analysis currently puts **GLM-5.3 Max immediately behind MiMo-V2.6-Pro among open-weight models**, with a score of 45 versus MiMo's 46. citeturn15view9

Thus “strong reasoning, especially Flash” is fair, but I would not place it in the same local-hardware chart as Qwen3.8, Gemma 4, or Dolphin. Even the “Flash” version still contains roughly 320B total parameters. citeturn17view10

Community uncensored GLM-5.3-Flash builds already exist, including quantized variants, but there is not yet one obviously canonical uncensored checkpoint with the same maturity and broad adoption that Huihui's Qwen releases have. Hugging Face currently shows several such GLM-5.3-Flash derivatives rather than a clear single standard. citeturn14search19

## Consumer hardware reality

The most useful way to rank these models is by **memory class**, because a global intelligence leaderboard is nearly useless when one entry is 27B and another is 1T.

### Around 16GB VRAM

**Qwen3.8-27B is possible, not luxurious.** IQ4_XS is about 14.3GB, while Q3 variants range from roughly 10.9 to 13.1GB. That leaves substantially more usable memory for context with Q3 than with a 14–15GB Q4. citeturn16view3

For this class of machine, Gemma's smaller family members and genuinely smaller Hermes-type models become increasingly attractive. Gemma 4 itself spans small E2B/E4B models, 12B, the 26B-A4B MoE, and 31B, giving the family unusually broad hardware coverage. citeturn17view5

I would therefore change **“Qwen3.8 can be squeezed into 16GB”** to **“Qwen3.8 is viable on 16GB with aggressive quantization and reduced context, but 24GB is the more natural target.”**

### Around 24GB VRAM

This is where **Qwen3.8-27B becomes exceptionally compelling**.

A Q4_K_M-sized checkpoint is around **16.5GB**, leaving materially more VRAM than Q5_K_M at 19.8GB. Q5 is absolutely feasible in some configurations, but Q4 gives much healthier space for cache and runtime overhead. citeturn16view3

That is why I would recommend **Q4_K_M or a similar high-quality 4-bit quant as the general 3090/4090 choice**, rather than automatically chasing Q5. The marginal benefit of an extra bit is often less useful than enough memory to avoid CPU offload or to keep a longer KV cache on-GPU.

The RTX 3090/4090 tier should therefore be considered the model's real sweet spot. NVIDIA specifies 24GB on the 4090. citeturn20search4

### Around 32GB VRAM

The RTX 5090 is notably better situated because NVIDIA gives it **32GB of GDDR7**, not 24GB. citeturn21search0

Qwen3.8's Q6 variants occupy approximately **22–25.3GB**, while Q8_0 is around **29GB**. That makes Q6 a particularly natural 5090 configuration: much higher precision than Q4 with useful memory still available for inference. citeturn16view3

Q8 technically enters the picture at 32GB, but a 29GB weight allocation does not leave much capacity for everything else, particularly long contexts. citeturn16view3turn17view0

### Long context changes everything

A model supporting 262K tokens does not mean you should configure 262K every time it starts.

Qwen3.8 supports **262,144 natively and up to 1,000,000 with RoPE/YaRN scaling**, but those are architectural limits. Qwen itself documents special configuration for the 1M mode. citeturn17view0

Gemma 4 similarly supports up to **256K** on its medium-sized models. citeturn17view5

For consumer inference, context length should be treated as a tunable memory budget. A 16–32K or 32–64K runtime configuration is often far more sensible than preallocating hundreds of thousands of tokens simply because the architecture permits it.

## What “uncensored” actually means in 2026

This is the biggest conceptual issue with almost every uncensored-model ranking: the word **“uncensored” bundles together technically different things**.

### Abliterated models

Huihui Qwen and many Gemma derivatives belong here.

Abliteration identifies internal directions associated with refusal behavior and edits model weights/activations so those directions are less likely to control the output. Huihui explicitly calls its own implementation an abliteration-based uncensored modification and describes recent selective-layer changes intended to preserve base capability. citeturn17view3

Its advantage is obvious: you can take an extremely strong contemporary foundation model such as Qwen3.8 and remove a large fraction of its refusal behavior **without needing a giant replacement training run**.

The downside is that the intervention can change other behavior. The 2026 cross-family study mentioned earlier found measurable shifts in risk disposition, confidence, verbosity, and uncertainty expression after abliteration. citeturn15view11

So:

**Abliterated ≠ identical base model with a boolean `refuse=False` flag.**

### Uncensored/steerable post-training

Dolphin and Hermes are conceptually different.

Dolphin explicitly states that the model owner determines its system prompt and alignment and that the model is intended not to impose its own ethical guidelines. citeturn16view10

Hermes 4 similarly targets “aligned to you,” broad neutrality, steerability, reasoning, structured outputs, and low refusal rates through post-training rather than merely deleting a refusal direction. citeturn18view7turn17view6

This can make such models feel more naturally cooperative than an aggressively abliterated instruction model, especially in roleplay, creative writing, or custom-persona applications.

The tradeoff is that their **base intelligence can age**. A perfectly tuned 2025-era 24B model can still lose to a much newer 2026 foundation model on difficult programming or agent tasks.

### “Heretic,” merges, and specialized RP models

This category is the least standardized.

Hugging Face now contains a large number of **Heretic, abliteration, fusion, merge, and “uncensored” Qwen/Gemma derivatives**, including rapidly appearing Qwen3.8 variants. The label by itself tells you much less than the exact model card, parent checkpoint, modification procedure, quantization, and chat template. citeturn14search5

The same applies to dedicated roleplay models. Cydonia, Magnum-type models, Euryale-style finetunes, and numerous creative-writing merges can outperform a general model **subjectively** on prose voice, character persistence, initiative, romance, dark themes, or roleplay format, while simultaneously being substantially worse at coding or factual reasoning. Current Hugging Face collections still contain models such as TheDrummer's Cydonia 24B family alongside hundreds of specialized RP checkpoints. citeturn14search10turn14search7

For that reason, I would **not put roleplay finetunes into the same numbered intelligence ranking**. They should have their own ranking based on style and preference testing.

### Offline does remove provider-side moderation, but not necessarily refusals

Your final sentence is essentially right with one semantic correction.

When the weights run entirely on your own machine, **there is no remote inference provider controlling the response or inspecting each prompt**. Qwen, Dolphin, Hermes and their quantized derivatives can be run with self-hosted runtimes documented by their respective model repositories. citeturn16view1turn16view8turn17view8

However:

> **offline = no provider-side censorship**  
> does not necessarily mean  
> **offline = zero refusal behavior**

An unmodified instruction-tuned model can still have refusal behavior encoded in its own weights. An abliterated or intentionally low-refusal finetune reduces that behavior, sometimes dramatically, but there is no universal industry definition or certification for “uncensored.” The recent research on abliteration also shows that changing refusal behavior can affect other dispositions. citeturn15view11

## Revised recommendation

I would rewrite your September 2026 list approximately like this:

### Best practical uncensored local model overall

**Huihui-Qwen3.8-27B-abliterated**

This is the model I would put first for a **24GB RTX 3090/4090 or 32GB RTX 5090**. It combines a genuinely state-of-the-art-for-its-size base with low-refusal modification, 262K native context, image understanding, very strong reasoning/coding/agent results, and an Apache-2.0 parent checkpoint. citeturn18view5turn18view1turn18view2turn17view3

For a 24GB card, **Q4 around 16–18GB is the safest general-purpose configuration**. Q5 can work but gives away useful context/runtime headroom. On the 32GB 5090, Q6 becomes especially attractive. citeturn16view3turn21search0

**Overall recommendation: ★★★★★**

### Best efficiency-focused alternative

**Gemma 4 26B-A4B uncensored / abliterated**

Its **25.2B total / 3.8B active** MoE architecture gives it a very attractive speed-to-quality ratio, with native 256K context and multimodality. It will not magically have the memory footprint of a 4B model, but its per-token compute load is dramatically smaller than a dense 25–27B architecture. citeturn17view4turn17view5

**Overall recommendation: ★★★★½**

### Best intentionally steerable rather than surgically abliterated

**Hermes 4**

Hermes remains the cleanest recommendation when the *philosophy* matters: the model is explicitly post-trained for broad user steerability, hybrid reasoning, tools/structured outputs, and low refusal rates rather than simply having a refusal vector removed. citeturn18view7turn17view6

Choose the model size according to hardware; 14B is much more local-friendly than 70B, while the broader Hermes ecosystem also contains 36B and much larger releases. citeturn19search16

**Overall recommendation: ★★★★½**

### Best older mature low-refusal model

**Dolphin 3.0 Mistral 24B**

Still excellent if you value predictable uncensored-chat behavior, low setup friction, and proven local deployment. The existence of a roughly 13GB Ollama configuration makes it especially convenient. But it should no longer be ranked above Gemma 4 or current Qwen3.8 on raw intelligence. citeturn17view8turn16view10

**Overall recommendation: ★★★½**

### Best raw open-weight intelligence

**MiMo-V2.6-Pro**

On the latest Artificial Analysis ranking checked for this report, this is the **#1 open-weight model**, with GLM-5.3 immediately behind it. Xiaomi's official repository lists MiMo-V2.6-Pro at **1T parameters**, making this a server/workstation/cluster-class model rather than a normal desktop download. citeturn15view9turn15view8

**Intelligence: ★★★★★**  
**Consumer-local practicality: ★**

### Best very-large agent/coding alternative

**GLM-5.3**, or **GLM-5.3-Flash** when efficiency matters at that scale.

GLM-5.3 is **744B-A40B** and GLM-5.3-Flash is **320B-A18B**. Both are vastly beyond single-consumer-GPU scale despite their sparse activation counts, although the official project supports several local/self-hosted serving stacks for people with sufficient hardware. citeturn17view9turn17view10

**Intelligence: ★★★★★**  
**Consumer-local practicality: ★–★★**

The resulting hierarchy is therefore:

> **For a 16GB GPU:** Qwen3.8-27B IQ4/Q3 if maximum intelligence matters, or a genuinely smaller model for more context/headroom. citeturn16view3  
>
> **For a 24GB RTX 3090/4090:** **Qwen3.8-27B abliterated Q4 is the strongest all-around recommendation.** citeturn16view3turn18view1  
>
> **For a 32GB RTX 5090:** **Qwen3.8-27B abliterated at Q5/Q6** is an even cleaner choice; the 5090 really has 32GB, not 24GB. citeturn16view3turn21search0  
>
> **For maximum tokens/sec at similar stored-model scale:** **Gemma 4 26B-A4B** deserves serious consideration because only 3.8B parameters are active per token. citeturn17view4  
>
> **For the most intentionally user-steerable behavior:** **Hermes 4** remains more conceptually attractive than simple abliteration. citeturn17view6turn18view7  
>
> **For pure capability with effectively unlimited hardware:** **MiMo-V2.6-Pro**, followed closely by **GLM-5.3** on the current independent open-weight ranking. citeturn15view9  
>
> **For RP/ERP:** treat specialized Cydonia/Magnum/Euryale/TheDrummer-style checkpoints as a separate subjective category; their stylistic advantages do not imply better reasoning or coding performance. Current Hugging Face activity confirms that this remains a large, fast-moving ecosystem rather than a single obvious winner. citeturn14search7turn14search10

So, with the hype removed, **your central conclusion survives the research**: **Qwen3.8-27B Abliterated is the model I would currently put at the top of a “best uncensored LLM you can realistically run yourself” list.** The two biggest corrections are that it is **not the absolute strongest open-weight model regardless of hardware**, and that a **24GB card should usually target Q4 rather than assuming Q5 plus huge context will fit comfortably**. MiMo-V2.6-Pro and GLM-5.3 occupy the raw-intelligence crown; Qwen3.8-27B occupies the much more useful **consumer-local capability crown**. citeturn15view9turn16view3turn18view1