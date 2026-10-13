"""Embed in BRIDGE_CODE before optional model/save hooks; no dependencies.

The app's extra_data.phone_studio_speed_extras selects per-image extras.
Missing values keep the notebook default (on). Launch-time precision is separate.
Stock IS_CHANGED fingerprints prevent an old accelerated image being returned
from cache after the switch changes, without discarding model/text caches.
Sources: ComfyUI execution.py, comfy_execution/caching.py, nodes.py.
"""

import contextvars as _ps_speed_contextvars
import functools as _ps_speed_functools
import inspect as _ps_speed_inspect
import os as _ps_speed_os

_PS_COMPATIBILITY_MODE = _ps_speed_os.environ.get('PHONE_STUDIO_COMPATIBILITY_MODE', '0') == '1'
_PS_SPEED_EXTRAS = _ps_speed_contextvars.ContextVar('phone_studio_speed_extras', default=not _PS_COMPATIBILITY_MODE)
_PS_SPEED_SWITCH_AVAILABLE = False


def _phone_studio_speed_extras_enabled():
    return not _PS_COMPATIBILITY_MODE and _PS_SPEED_EXTRAS.get()


def _ps_is_edit_graph(prompt):
    if not isinstance(prompt, dict):
        return False
    edit_nodes = {'LoadImage', 'LoadImageMask', 'VAEEncode', 'VAEEncodeForInpaint',
                  'SetLatentNoiseMask', 'InpaintModelConditioning', 'ImagePadForOutpaint'}
    for node in prompt.values():
        if not isinstance(node, dict):
            continue
        kind = node.get('class_type', '')
        if kind in edit_nodes or (isinstance(kind, str) and kind.startswith('INPAINT_')):
            return True
        if kind == 'SaveImage' and isinstance(node.get('inputs'), dict):
            if str(node['inputs'].get('filename_prefix', '')).startswith('PhoneStudioEdit'):
                return True
    return False


def _ps_speed_requested(extra_data, prompt=None):
    if not isinstance(extra_data, dict):
        return not _PS_COMPATIBILITY_MODE and not _ps_is_edit_graph(prompt)
    value = extra_data.get('phone_studio_speed_extras', True)
    if type(value) is not bool:
        raise ValueError('phone_studio_speed_extras must be a Boolean')
    return False if _PS_COMPATIBILITY_MODE or _ps_is_edit_graph(prompt) else value


def _ps_install_speed_switch():
    global _PS_SPEED_SWITCH_AVAILABLE
    try:
        import execution as _ps_speed_execution
        import nodes as _ps_speed_nodes
        executor = _ps_speed_execution.PromptExecutor
        marker = '_phone_studio_speed_switch_v1'
        if getattr(executor.execute, marker, False):
            _PS_SPEED_SWITCH_AVAILABLE = True
            return
        hooks = []
        for name in ('execute', 'execute_async'):
            original = getattr(executor, name, None)
            if original is None:
                continue
            signature = _ps_speed_inspect.signature(original)
            if not {'self', 'prompt', 'prompt_id', 'extra_data'} <= set(signature.parameters):
                raise RuntimeError('ComfyUI executor API changed')

            def make_wrapper(fn, sig):
                def select_flag(args, kwargs):
                    bound = sig.bind(*args, **kwargs)
                    bound.apply_defaults()
                    return _ps_speed_requested(bound.arguments.get('extra_data'), bound.arguments.get('prompt'))

                if _ps_speed_inspect.iscoroutinefunction(fn):
                    @_ps_speed_functools.wraps(fn)
                    async def wrapped(*args, **kwargs):
                        token = _PS_SPEED_EXTRAS.set(select_flag(args, kwargs))
                        try:
                            return await fn(*args, **kwargs)
                        finally:
                            _PS_SPEED_EXTRAS.reset(token)
                else:
                    @_ps_speed_functools.wraps(fn)
                    def wrapped(*args, **kwargs):
                        token = _PS_SPEED_EXTRAS.set(select_flag(args, kwargs))
                        try:
                            return fn(*args, **kwargs)
                        finally:
                            _PS_SPEED_EXTRAS.reset(token)
                setattr(wrapped, marker, True)
                return wrapped

            hooks.append((name, make_wrapper(original, signature)))

        classes = (_ps_speed_nodes.KSampler, _ps_speed_nodes.SaveImage)
        if any(cls.__module__ != 'nodes' or hasattr(cls, 'IS_CHANGED') for cls in classes):
            raise RuntimeError('stock sampler/save fingerprint API is unavailable or already customized')

        # Only a cheap Boolean cache fingerprint changes. Standard sampling,
        # model/CLIP caches, graph fields and class execution methods stay intact.
        def fingerprint(**inputs):
            return _phone_studio_speed_extras_enabled()

        for cls in classes:
            cls.IS_CHANGED = staticmethod(fingerprint)
        for name, wrapped in hooks:
            setattr(executor, name, wrapped)
        _PS_SPEED_SWITCH_AVAILABLE = True
        print('[phone-studio] Per-image speed switch ready; sampling/save caches distinguish on/off.')
    except Exception as error:
        print(f'[phone-studio] Per-image speed switch unavailable ({error}); notebook defaults retained.')


_ps_install_speed_switch()


@web.middleware
async def _ps_speed_switch_guard(request, handler):
    if request.method == 'POST' and request.path == '/prompt':
        try:
            body = await request.json()
        except Exception:
            body = None  # Standard handler reports malformed request JSON.
        extra = body.get('extra_data') if isinstance(body, dict) else None
        if isinstance(extra, dict) and 'phone_studio_speed_extras' in extra:
            value = extra['phone_studio_speed_extras']
            message = None
            if type(value) is not bool:
                message = 'The extra acceleration setting must be true or false.'
            elif not _PS_SPEED_SWITCH_AVAILABLE:
                message = 'This ComfyUI version cannot switch image acceleration. Update/rerun the notebook bridge.'
            if message:
                return web.json_response({
                    'error': {'type': 'phone_studio_speed_switch_unavailable',
                              'message': message, 'details': message, 'extra_info': {}},
                    'node_errors': {},
                }, status=400)
    return await handler(request)


PromptServer.instance.app.middlewares.append(_ps_speed_switch_guard)
