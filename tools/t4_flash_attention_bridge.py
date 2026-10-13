"""Optional bridge snippet for the pinned, patched T4 attention extension.

Embed this source in BRIDGE_CODE after the existing checkpoint-load wrappers.
It is inactive unless PHONE_STUDIO_T4_FLASH_ATTENTION=1. The installer must
produce a matching manifest; an ordinary flash-attention-turing install is not
accepted. No PyTorch operator or imported ComfyUI attention reference is patched.

Sources inspected:
https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/ldm/modules/attention.py
https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/model_patcher.py
https://github.com/ssiu/flash-attention-turing/tree/9ef98fcb506bb1e2fe3cece50935e2935bf6b124
"""


def _ps_install_t4_flash_attention():
    import functools as _t4_functools
    import hashlib as _t4_hashlib
    import importlib.util as _t4_importlib
    import inspect as _t4_inspect
    import json as _t4_json
    import logging as _t4_logging
    import math as _t4_math
    import os as _t4_os
    from pathlib import Path as _T4_Path
    import sys as _t4_sys

    if _t4_os.environ.get('PHONE_STUDIO_T4_FLASH_ATTENTION', '0') != '1':
        return

    _t4_log = _t4_logging.getLogger('phone-studio.t4-attention')
    _t4_commit = '9ef98fcb506bb1e2fe3cece50935e2935bf6b124'
    _t4_patch = 'phone-studio-t4-forward-v1'
    _t4_module_name = 'phone_studio_flash_attn_turing'
    _t4_root = _T4_Path('/content/phone_studio_t4_flash')
    _t4_runtime = _t4_root / 'runtime'
    _t4_stamp = _t4_root / 'install.json'

    try:
        import torch as _t4_torch
        import comfy.sd as _t4_sd
        import comfy.model_base as _t4_model_base
        from comfy.ldm.modules import attention as _t4_attention

        if not _t4_torch.cuda.is_available():
            raise RuntimeError('CUDA is unavailable')
        if _t4_torch.cuda.get_device_capability(0) != (7, 5):
            raise RuntimeError('this extension is restricted to T4/Turing SM7.5')
        if (_t4_root.is_symlink() or _t4_runtime.is_symlink()
                or _t4_stamp.is_symlink() or not _t4_stamp.is_file()
                or _t4_stamp.stat().st_size > 65536):
            raise RuntimeError('a matching local installer manifest is required')
        _t4_manifest = _t4_json.loads(_t4_stamp.read_text(encoding='utf-8'))
        _t4_identity = {
            'schema': 1,
            'commit': _t4_commit,
            'patch': _t4_patch,
            'module': _t4_module_name,
            'torch_version': str(_t4_torch.__version__),
            'torch_cuda': str(_t4_torch.version.cuda),
            'python_cache_tag': _t4_sys.implementation.cache_tag,
            'runtime_dir': str(_t4_runtime),
            'preflight_passed': True,
        }
        if not isinstance(_t4_manifest, dict) or any(
                _t4_manifest.get(key) != value
                for key, value in _t4_identity.items()):
            raise RuntimeError('installer manifest does not match this runtime/build')
        _t4_binary = _T4_Path(_t4_manifest.get('module_file', ''))
        if (not _t4_binary.is_absolute() or _t4_binary.is_symlink()
                or _t4_binary.parent != _t4_runtime
                or _t4_binary.resolve().parent != _t4_runtime.resolve()
                or not _t4_binary.name.startswith(_t4_module_name + '.')
                or _t4_binary.suffix != '.so' or not _t4_binary.is_file()):
            raise RuntimeError('installer native module path is invalid')
        _t4_digest = _t4_hashlib.sha256()
        with _t4_binary.open('rb') as _t4_binary_file:
            for _t4_chunk in iter(lambda: _t4_binary_file.read(1024 * 1024), b''):
                _t4_digest.update(_t4_chunk)
        if _t4_digest.hexdigest() != _t4_manifest.get('module_sha256'):
            raise RuntimeError('installer native module hash has changed')

        # Fail closed on an upstream hook/signature change. The documented
        # per-model override is read inside existing decorated attention calls,
        # including references imported before this custom bridge was loaded.
        _t4_default = _t4_attention.attention_pytorch
        _t4_default_raw = _t4_inspect.unwrap(_t4_default)
        _t4_required = ('q', 'k', 'v', 'heads', 'mask', 'attn_precision',
                        'skip_reshape', 'skip_output_reshape')
        if tuple(_t4_inspect.signature(_t4_default_raw).parameters)[:8] != _t4_required:
            raise RuntimeError('ComfyUI attention signature is not supported')
        if ('optimized_attention_override' not in
                _t4_inspect.getsource(_t4_attention.wrap_attn)):
            raise RuntimeError('ComfyUI per-model attention override is unavailable')
        if (_t4_attention.optimized_attention is not _t4_default
                or _t4_attention.optimized_attention_masked is not _t4_default):
            raise RuntimeError('the ordinary PyTorch attention baseline is required')
        if not hasattr(_t4_model_base, 'SDXL'):
            raise RuntimeError('ComfyUI SDXL model class is unavailable')
        if not callable(getattr(_t4_sd, 'load_checkpoint_guess_config', None)):
            raise RuntimeError('ComfyUI checkpoint loader is unavailable')

        # Load only the isolated binary named by the matching manifest. An
        # unrelated module with the same import name is never used accidentally.
        _t4_native = _t4_sys.modules.get(_t4_module_name)
        if _t4_native is None:
            _t4_spec = _t4_importlib.spec_from_file_location(
                _t4_module_name, str(_t4_binary))
            if _t4_spec is None or _t4_spec.loader is None:
                raise RuntimeError('native extension loader is unavailable')
            _t4_native = _t4_importlib.module_from_spec(_t4_spec)
            _t4_spec.loader.exec_module(_t4_native)
            _t4_sys.modules[_t4_module_name] = _t4_native
        if (getattr(_t4_native, '__phone_studio_commit__', None) != _t4_commit
                or getattr(_t4_native, '__phone_studio_patch__', None) != _t4_patch
                or _T4_Path(getattr(_t4_native, '__file__', '')).resolve()
                != _t4_binary.resolve()
                or not callable(getattr(_t4_native, 'fwd', None))):
            raise RuntimeError('native extension identity/API does not match')

        _t4_capabilities = {0: (7, 5)}
        _t4_first_use = False
        _t4_is_compiling = getattr(
            getattr(_t4_torch, 'compiler', None), 'is_compiling', None)

        def _ps_t4_attention_override(
                default_attention, q, k, v, heads, mask=None,
                attn_precision=None, skip_reshape=False,
                skip_output_reshape=False, **kwargs):
            nonlocal _t4_first_use

            def _t4_fallback():
                return default_attention(
                    q, k, v, heads, mask=mask, attn_precision=attn_precision,
                    skip_reshape=skip_reshape,
                    skip_output_reshape=skip_output_reshape, **kwargs)

            # The phone can disable per-image extras while keeping the native
            # build/model warm. Resolve the executor-scoped policy at each call.
            _t4_speed_policy = globals().get('_phone_studio_speed_extras_enabled')
            if callable(_t4_speed_policy) and not _t4_speed_policy():
                return _t4_fallback()

            # Only the known PyTorch path is replaced. Future preferred kernels,
            # masks, custom options, grouped heads and backward/tracing calls
            # retain the original implementation and all of its arguments.
            if (default_attention is not _t4_default_raw or mask is not None
                    or type(heads) is not int or not 1 <= heads <= 64
                    or type(skip_reshape) is not bool
                    or type(skip_output_reshape) is not bool
                    or _t4_torch.is_grad_enabled()
                    or _t4_torch.jit.is_tracing() or _t4_torch.jit.is_scripting()
                    or (callable(_t4_is_compiling) and _t4_is_compiling())
                    or any(type(t) is not _t4_torch.Tensor for t in (q, k, v))):
                return _t4_fallback()
            _t4_known_keys = {'transformer_options', '_inside_attn_wrapper',
                              'scale', 'enable_gqa'}
            if (any(key not in _t4_known_keys for key in kwargs)
                    or ('enable_gqa' in kwargs
                        and type(kwargs['enable_gqa']) is not bool)
                    or kwargs.get('enable_gqa', False)):
                return _t4_fallback()
            if (_t4_attention.get_attn_precision(attn_precision, q.dtype)
                    not in (None, _t4_torch.float16)):
                return _t4_fallback()
            if any(t.device != q.device or not t.is_cuda
                   or t.dtype != _t4_torch.float16 or t.requires_grad
                   or t.layout != _t4_torch.strided for t in (q, k, v)):
                return _t4_fallback()
            _t4_device = q.device.index
            if _t4_device not in _t4_capabilities:
                _t4_capabilities[_t4_device] = (
                    _t4_torch.cuda.get_device_capability(q.device))
            if _t4_capabilities[_t4_device] != (7, 5):
                return _t4_fallback()

            if skip_reshape:
                # ComfyUI skip_reshape inputs are B,H,L,D, not B,L,H,D.
                if (any(t.ndim != 4 for t in (q, k, v))
                        or any(t.shape[0] != q.shape[0]
                               or t.shape[1] != heads or t.shape[3] != 64
                               for t in (q, k, v))
                        or k.shape[2] != v.shape[2]):
                    return _t4_fallback()
                _t4_batch, _, _t4_q_len, _t4_dim = q.shape
                _t4_k_len = k.shape[2]
            else:
                if (any(t.ndim != 3 for t in (q, k, v))
                        or any(t.shape[0] != q.shape[0]
                               or t.shape[2] != heads * 64 for t in (q, k, v))
                        or k.shape[1] != v.shape[1]):
                    return _t4_fallback()
                _t4_batch, _t4_q_len, _ = q.shape
                _t4_dim, _t4_k_len = 64, k.shape[1]
            # Bound this experimental path to ordinary SDXL workloads. Larger
            # batches/sequences remain eligible for the stock memory policy.
            if (not 1 <= _t4_batch <= 4 or not 1 <= _t4_q_len <= 16384
                    or not 1 <= _t4_k_len <= 16384
                    or sum(t.numel() * t.element_size() for t in (q, k, v))
                    > 128 * 1024 * 1024):
                return _t4_fallback()
            _t4_scale = kwargs.get('scale', None)
            if _t4_scale is None:
                _t4_scale = _t4_dim ** -0.5
            elif (type(_t4_scale) not in (int, float)
                    or not _t4_math.isfinite(_t4_scale)):
                return _t4_fallback()
            # The native binding takes a positive float32 scale. Do not send
            # a Python double that would underflow to zero or overflow there.
            if not 1.1754943508222875e-38 <= _t4_scale <= 3.4028234663852886e38:
                return _t4_fallback()

            # These transformations never cast Q/K/V. Full contiguous storage
            # is mandatory: checking stride(-1) alone is unsafe for this kernel.
            with _t4_torch.cuda.device(q.device):
                if skip_reshape:
                    _t4_q, _t4_k, _t4_v = (
                        t.transpose(1, 2).contiguous() for t in (q, k, v))
                else:
                    _t4_q, _t4_k, _t4_v = (
                        t.reshape(_t4_batch, t.shape[1], heads, _t4_dim).contiguous()
                        for t in (q, k, v))
                # A contiguous narrow view can still have an unaligned storage
                # offset; the kernel assumes 16-byte vector-load alignment.
                if any(t.data_ptr() % 16 for t in (_t4_q, _t4_k, _t4_v)):
                    return _t4_fallback()
                # The pinned installer patches the CUDA launch to PyTorch's
                # current stream. Do not catch a failed native CUDA launch and
                # retry SDPA on a potentially poisoned CUDA context.
                _t4_out, _t4_lse = _t4_native.fwd(
                    _t4_q, _t4_k, _t4_v, float(_t4_scale), False)
                del _t4_lse
                if skip_output_reshape:
                    _t4_result = _t4_out.transpose(1, 2)
                else:
                    _t4_result = _t4_out.reshape(
                        _t4_batch, _t4_q_len, heads * _t4_dim)
            if not _t4_first_use:
                _t4_first_use = True
                _t4_log.info('[phone-studio] T4 FlashAttention used for eligible '
                             'SDXL FP16 head-64 attention; other calls use PyTorch.')
            return _t4_result

        _t4_original_loader = _t4_sd.load_checkpoint_guess_config

        @_t4_functools.wraps(_t4_original_loader)
        def _ps_load_checkpoint_with_t4_attention(*args, **kwargs):
            _t4_loaded = _t4_original_loader(*args, **kwargs)
            if (not isinstance(_t4_loaded, (tuple, list)) or not _t4_loaded
                    or _t4_loaded[0] is None):
                return _t4_loaded
            _t4_patcher = _t4_loaded[0]
            # Inspect the detected class instead of assuming a model family
            # from its filename. CLIP/VAE and non-SDXL models are untouched.
            if type(getattr(_t4_patcher, 'model', None)) is not _t4_model_base.SDXL:
                return _t4_loaded
            try:
                _t4_options = _t4_patcher.model_options
                if not isinstance(_t4_options, dict):
                    return _t4_loaded
                _t4_transformer = _t4_options.get('transformer_options', {})
                if (not isinstance(_t4_transformer, dict)
                        or 'optimized_attention_override' in _t4_transformer):
                    return _t4_loaded
                # Do not displace a checkpoint's preferred/quantized attention.
                if any(isinstance(module, _t4_attention.ComfyAttention)
                       and module.function is not None
                       for module in _t4_patcher.model.diffusion_model.modules()):
                    return _t4_loaded
                _t4_clone = _t4_patcher.clone()
                _t4_clone.model_options = dict(_t4_clone.model_options)
                _t4_clone.model_options['transformer_options'] = dict(
                    _t4_clone.model_options.get('transformer_options', {}))
                _t4_clone.model_options['transformer_options'][
                    'optimized_attention_override'] = _ps_t4_attention_override
                _t4_result = [_t4_clone, *_t4_loaded[1:]]
                return tuple(_t4_result) if isinstance(_t4_loaded, tuple) else _t4_result
            except (AttributeError, TypeError, KeyError) as _t4_exc:
                _t4_log.warning('[phone-studio] T4 attention model hook skipped: %s',
                                _t4_exc)
                return _t4_loaded

        _t4_sd.load_checkpoint_guess_config = _ps_load_checkpoint_with_t4_attention
        _t4_log.info('[phone-studio] Optional T4 FlashAttention hook enabled; '
                     'no speed or image-equivalence result has been measured.')
    except Exception as _t4_exc:
        # Setup failure occurs before any custom kernel is dispatched. Existing
        # PyTorch attention remains installed; no partial model hook is left.
        _t4_log.warning('[phone-studio] Optional T4 FlashAttention unavailable '
                        '(%s); using the existing PyTorch path.', _t4_exc)


_ps_install_t4_flash_attention()
