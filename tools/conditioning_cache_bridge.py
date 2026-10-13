"""Optional render-local SDXL text-conditioning cache for BRIDGE_CODE.

Embed after the existing checkpoint-load wrappers and T4 attention snippet,
before the bridge's route/node registrations. Inactive unless
PHONE_STUDIO_FAST_CONDITIONING_CACHE=1. No dependency is installed here.

This caches upstream CONDCrossAttn.concat plus its usual FP16 CUDA transfer;
attention projections, sampling arithmetic and global COND classes are untouched.
Current primary-source contracts:
https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/conds.py
https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/samplers.py
https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/sampler_helpers.py
https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/model_base.py
https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/patcher_extension.py
"""


def _ps_install_conditioning_cache():
    import functools
    import inspect
    import logging
    import math
    import os
    import types

    if os.environ.get('PHONE_STUDIO_FAST_CONDITIONING_CACHE', '0') != '1':
        return
    log = logging.getLogger('phone-studio.conditioning-cache')
    marker = '_phone_studio_conditioning_cache_v1'
    wrapper_key = 'phone_studio_conditioning_cache_v1'
    budget = 8 * 1024 * 1024  # Private CPU snapshots plus retained GPU tensors.
    margin = 64 * 1024 * 1024
    skipped = set()

    def skip(reason):
        if reason not in skipped and len(skipped) < 16:
            skipped.add(reason)
            log.info('[phone-studio] Conditioning cache skipped: %s; stock path retained.', reason)

    try:
        import torch
        import comfy.conds as conds_module
        import comfy.model_base as model_base
        import comfy.model_management as management
        import comfy.model_patcher as patchers
        import comfy.patcher_extension as extension
        import comfy.sampler_helpers as helpers
        import comfy.samplers as samplers
        import comfy.sd as sd
        import comfy.supported_models as supported_models
        import latent_preview
        from comfy.ldm.modules import attention
        from comfy.ldm.modules.diffusionmodules.openaimodel import UNetModel

        if getattr(sd.load_checkpoint_guess_config, marker, False):
            return
        if (os.environ.get('PHONE_STUDIO_FAST_DENOISE_CACHE', '0') == '1'
                or os.environ.get('PHONE_STUDIO_T4_FLASH_ATTENTION', '0') == '1'):
            raise RuntimeError('turn EasyCache and T4 FlashAttention off for a separate comparison')
        if not torch.cuda.is_available() or torch.cuda.get_device_capability(0) != (7, 5):
            raise RuntimeError('a CUDA T4/Turing SM7.5 runtime is required')
        is_compiling = getattr(getattr(torch, 'compiler', None), 'is_compiling', None)
        if not callable(is_compiling):
            raise RuntimeError('PyTorch compile-state guard is unavailable')
        cross_class = conds_module.CONDCrossAttn
        original_concat = cross_class.concat
        sample_method = inspect.unwrap(samplers.KSAMPLER.sample)
        expected = ('self', 'model_wrap', 'sigmas', 'extra_args', 'callback',
                    'noise', 'latent_image', 'denoise_mask', 'disable_pbar')
        if tuple(inspect.signature(sample_method).parameters) != expected:
            raise RuntimeError('ComfyUI sampler signature changed')
        if (tuple(inspect.signature(original_concat).parameters) != ('self', 'others')
                or cross_class.process_cond is not conds_module.CONDRegular.process_cond
                or cross_class._copy_with is not conds_module.CONDRegular._copy_with
                or tuple(inspect.signature(patchers.ModelPatcher.add_wrapper_with_key).parameters)
                != ('self', 'wrapper_type', 'key', 'wrapper')):
            raise RuntimeError('ComfyUI conditioning/model wrapper API changed')
        inner_source = inspect.getsource(inspect.unwrap(samplers.CFGGuider.inner_sample))
        if ('process_conds(' not in inner_source
                or 'WrappersMP.SAMPLER_SAMPLE' not in inner_source
                or inner_source.index('process_conds(') > inner_source.index('WrappersMP.SAMPLER_SAMPLE')
                or 'model.wrappers' not in inspect.getsource(helpers.prepare_model_patcher)
                or 'cast_to_device(context, device, dtype)' not in
                inspect.getsource(inspect.unwrap(model_base.BaseModel._apply_model))):
            raise RuntimeError('ComfyUI render/cast hook contract changed')
        sampler_function = samplers.k_diffusion_sampling.sample_dpmpp_2m
        callback_codes = tuple(
            code for code in inspect.unwrap(latent_preview.prepare_callback).__code__.co_consts
            if isinstance(code, types.CodeType) and code.co_name == 'callback')
        if not callback_codes:
            raise RuntimeError('stock preview callback contract changed')
        patcher_types = (patchers.ModelPatcher, patchers.CoreModelPatcher)

        def empty(value):
            if isinstance(value, dict):
                return all(empty(item) for item in value.values())
            if isinstance(value, (list, tuple)):
                return not value
            return value is None

        def own_wrappers(registry):
            if not isinstance(registry, dict):
                return False
            for stage, groups in registry.items():
                if not isinstance(groups, dict):
                    return False
                for key, functions in groups.items():
                    if not isinstance(functions, list):
                        return False
                    if functions and (stage != extension.WrappersMP.SAMPLER_SAMPLE
                                      or key != wrapper_key
                                      or any(fn is not sample_with_cache for fn in functions)):
                        return False
            return True

        def plain_options(options):
            if not isinstance(options, dict) or set(options) - {'transformer_options', 'to_load_options'}:
                return False
            transformer = options.get('transformer_options', {})
            load_options = options.get('to_load_options', {})
            if (not isinstance(transformer, dict) or not isinstance(load_options, dict)
                    or set(transformer) - {'wrappers', 'callbacks', 'sample_sigmas'}
                    or set(load_options) - {'wrappers', 'callbacks'}):
                return False
            return all(own_wrappers(value.get('wrappers', {}))
                       and empty(value.get('callbacks', {}))
                       for value in (transformer, load_options))

        def model_reason(patcher):
            if type(patcher) not in patcher_types:
                return 'custom model patcher'
            model = patcher.model
            if (type(model) is not model_base.SDXL
                    or type(model.model_config) is not supported_models.SDXL
                    or type(model.diffusion_model) is not UNetModel
                    or model.model_config.custom_operations is not None
                    or model.model_config.quant_config is not None):
                return 'only stock SDXL base models are supported'
            if (model.get_dtype_inference() != torch.float16
                    or model.diffusion_model.training):
                return 'only evaluation-mode FP16 inference is supported'
            if (not plain_options(patcher.model_options)
                    or not own_wrappers(patcher.wrappers)
                    or not empty(patcher.callbacks)
                    or any(getattr(patcher, key, None) for key in
                           ('object_patches', 'weight_wrapper_patches', 'injections',
                            'additional_models', 'hook_patches', 'forced_hooks', 'current_hooks'))):
                return 'custom model, sampler, attention, or conditioning hooks'
            attachments = patcher.attachments
            if (not isinstance(attachments, dict) or set(attachments) - {'lora_metadata'}
                    or ('lora_metadata' in attachments
                        and not isinstance(attachments['lora_metadata'], dict))):
                return 'custom model attachments'
            for module in model.diffusion_model.modules():
                if (any(getattr(module, key, None) for key in
                        ('_forward_hooks', '_forward_pre_hooks', '_backward_hooks',
                         '_torchdynamo_orig_callable'))
                        or 'forward' in module.__dict__ or '_forward' in module.__dict__
                        or (isinstance(module, attention.ComfyAttention)
                            and module.function is not None)):
                    return 'custom module hooks or preferred attention'
            return None

        def checked_model_reason(patcher):
            try:
                return model_reason(patcher)
            except (AttributeError, TypeError, KeyError):
                return 'ComfyUI model hook API changed'

        def sample_with_cache(executor, model_wrap, sigmas, extra_args, callback,
                              noise, latent_image=None, denoise_mask=None, disable_pbar=False):
            def stock(reason):
                skip(reason)
                return executor(model_wrap, sigmas, extra_args, callback, noise,
                                latent_image, denoise_mask, disable_pbar)

            speed_extras = globals().get('_phone_studio_speed_extras_enabled')
            if callable(speed_extras) and not speed_extras():
                return stock('speed extras are off for this phone request')
            sampler = executor.class_obj
            if (type(sampler) is not samplers.KSAMPLER
                    or inspect.unwrap(getattr(executor.original, '__func__', executor.original))
                    is not sample_method
                    or sampler.sampler_function is not sampler_function
                    or sampler.extra_options or sampler.inpaint_options
                    or type(model_wrap) is not samplers.CFGGuider
                    or model_wrap.cfg != 6.5
                    or torch.is_grad_enabled() or is_compiling()
                    or torch.jit.is_tracing() or torch.jit.is_scripting()):
                return stock('stock CFG 6.5 DPM++ 2M inference is required')
            if (denoise_mask is not None or type(noise) is not torch.Tensor
                    or noise.ndim != 4 or noise.shape[0] != 1 or noise.shape[1] != 4
                    or not noise.is_cuda or noise.requires_grad
                    or type(sigmas) is not torch.Tensor or sigmas.ndim != 1
                    or sigmas.numel() not in (19, 25)
                    or sigmas.device != noise.device
                    or (callback is not None and (type(callback) is not types.FunctionType
                                                 or callback.__code__ not in callback_codes))):
                return stock('batch-one two-preset sampling with the stock progress callback is required')
            if (not isinstance(extra_args, dict)
                    or set(extra_args) - {'model_options', 'seed'}
                    or not plain_options(extra_args.get('model_options', {}))
                    or not plain_options(model_wrap.model_options)):
                return stock('custom runtime sampling options')
            reason = checked_model_reason(model_wrap.model_patcher)
            if reason:
                return stock(reason)
            if (model_wrap.inner_model is not model_wrap.model_patcher.model
                    or model_wrap.inner_model.current_patcher is not model_wrap.model_patcher
                    or model_wrap.model_patcher.load_device != noise.device):
                return stock('model/device identity changed')
            device = noise.device
            with torch.cuda.device(device):
                if torch.cuda.get_device_capability(device) != (7, 5):
                    return stock('only T4/Turing SM7.5 is supported')
                if torch.cuda.mem_get_info(device)[0] < budget + margin:
                    return stock('insufficient free CUDA memory for the bounded cache')
                stream_id = torch.cuda.current_stream(device).cuda_stream
            original_conds = model_wrap.conds
            if not isinstance(original_conds, dict) or set(original_conds) != {'positive', 'negative'}:
                return stock('one plain positive and negative condition are required')
            source_tensors = []
            allowed_keys = {'cross_attn', 'pooled_output', 'model_conds', 'uuid'}
            for name in ('positive', 'negative'):
                entries = original_conds[name]
                if (not isinstance(entries, list) or len(entries) != 1
                        or not isinstance(entries[0], dict) or set(entries[0]) - allowed_keys):
                    return stock('scheduled, masked, regional, or custom conditioning')
                model_conds = entries[0].get('model_conds')
                if (not isinstance(model_conds, dict) or set(model_conds) != {'c_crossattn', 'y'}
                        or type(model_conds['c_crossattn']) is not cross_class
                        or type(model_conds['y']) is not conds_module.CONDRegular):
                    return stock('stock SDXL cross-attention and ADM conditioning are required')
                tensor = model_conds['c_crossattn'].cond
                if (type(tensor) is not torch.Tensor or tensor.ndim != 3
                        or tuple(tensor.shape)[::2] != (1, 2048)
                        or not 1 <= tensor.shape[1] <= 308
                        or tensor.device.type != 'cpu' or tensor.requires_grad
                        or tensor.layout != torch.strided
                        or tensor.dtype not in (torch.float16, torch.float32)):
                    return stock('bounded CPU [1,L,2048] text embeddings are required')
                source_tensors.append(tensor)
            snapshot_bytes = sum(t.numel() * t.element_size() for t in source_tensors)
            maximum_length = math.lcm(*(t.shape[1] for t in source_tensors))
            first_output_bytes = 2 * maximum_length * 2048 * 2
            if snapshot_bytes + first_output_bytes > budget:
                return stock('conditioning exceeds the 8 MiB total budget')

            # Copies isolate this render from node-output caching and lack of
            # version counters on inference tensors. Stock SDXL only reads them.
            with torch.inference_mode(False), torch.no_grad():
                snapshots = [tensor.detach().clone() for tensor in source_tensors]
            source_ids = {id(tensor) for tensor in snapshots}
            cache = {}
            retained_bytes = snapshot_bytes
            hits = misses = 0

            class RenderCrossAttn(cross_class):
                def concat(self, others):
                    nonlocal retained_bytes, hits, misses
                    inputs = [self, *others]
                    tensors = [item.cond for item in inputs]
                    # Stock process_cond returns the same source for batch one.
                    # An unexpected repeat/view/condition keeps ordinary concat.
                    if (len(inputs) not in (1, 2)
                            or any(type(item) is not RenderCrossAttn for item in inputs)
                            or any(id(tensor) not in source_ids for tensor in tensors)
                            or torch.cuda.current_stream(device).cuda_stream != stream_id):
                        skip('conditioning batch identity or CUDA stream changed')
                        return original_concat(self, others)
                    key = (tuple((id(tensor), tuple(tensor.shape), tuple(tensor.stride()), tensor.dtype)
                                 for tensor in tensors), device, torch.float16, stream_id)
                    if key in cache:
                        hits += 1
                        return cache[key]
                    output_length = math.lcm(*(tensor.shape[1] for tensor in tensors))
                    output_bytes = len(tensors) * output_length * 2048 * 2
                    if len(cache) >= 4 or retained_bytes + output_bytes > budget:
                        skip('render-local cache layout/byte cap reached')
                        return original_concat(self, others)
                    # Preserve upstream CPU concatenation/padding and the same
                    # cast operation used by BaseModel. No early rounding.
                    combined = original_concat(self, others)
                    with torch.cuda.device(device):
                        output = management.cast_to_device(combined, device, torch.float16)
                    cache[key] = output
                    retained_bytes += output_bytes
                    misses += 1
                    return output

            render_conds = dict(original_conds)
            for name, snapshot in zip(('positive', 'negative'), snapshots):
                entry = dict(original_conds[name][0])
                entry['model_conds'] = dict(entry['model_conds'])
                entry['model_conds']['c_crossattn'] = RenderCrossAttn(snapshot)
                render_conds[name] = [entry]
            del entry, snapshot
            model_wrap.conds = render_conds
            try:
                # Numerical/CUDA failures propagate; never retry a failed GPU
                # call on another path. No cache survives an interrupted render.
                return executor(model_wrap, sigmas, extra_args, callback, noise,
                                latent_image, denoise_mask, disable_pbar)
            finally:
                model_wrap.conds = original_conds
                cache.clear()
                snapshots.clear()
                render_conds.clear()
                log.info('[phone-studio] Conditioning cache released: hits=%d misses=%d retained_bytes=%d cap_bytes=%d.',
                         hits, misses, retained_bytes, budget)

        original_loader = sd.load_checkpoint_guess_config

        @functools.wraps(original_loader)
        def load_with_cache(*args, **kwargs):
            loaded = original_loader(*args, **kwargs)
            if not isinstance(loaded, (tuple, list)) or not loaded or loaded[0] is None:
                return loaded
            patcher = loaded[0]
            reason = checked_model_reason(patcher)
            if reason:
                skip(reason)
                return loaded
            # Ordinary ModelPatcher clones share weights and preserve wrappers;
            # adding ours does not force full residency or modify CLIP/VAE.
            try:
                clone = patcher.clone()
                if not any(fn is sample_with_cache for fn in
                           clone.get_wrappers(extension.WrappersMP.SAMPLER_SAMPLE, wrapper_key)):
                    clone.add_wrapper_with_key(extension.WrappersMP.SAMPLER_SAMPLE,
                                               wrapper_key, sample_with_cache)
            except (AttributeError, TypeError, KeyError):
                skip('ComfyUI model clone/wrapper API changed')
                return loaded
            result = [clone, *loaded[1:]]
            return tuple(result) if isinstance(loaded, tuple) else result

        setattr(load_with_cache, marker, True)
        sd.load_checkpoint_guess_config = load_with_cache
        log.info('[phone-studio] Optional conditioning cache hook enabled (8 MiB, render-local); no speed or image-equivalence result measured.')
    except Exception as error:
        # Initialization/API checks occur before attaching the loader hook and
        # before any optional tensor transfer. Unsupported installs stay stock.
        log.warning('[phone-studio] Conditioning cache unavailable (%s); stock path retained.', error)


_ps_install_conditioning_cache()
