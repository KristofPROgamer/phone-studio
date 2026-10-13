"""CPU/mock checks of worker setup policy; no notebook/GPU/bootstrap is run."""
import ast
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import types

import pytest

from tools import edit_worker_setup as editing
from tools import worker_runtime_setup as worker

ROOT = Path(__file__).resolve().parents[2]


def notebook_sources():
    notebook = json.loads((ROOT / 'PHONE_STUDIO_COLAB.ipynb').read_text(encoding='utf-8'))
    return notebook, [''.join(c['source']) for c in notebook['cells']]


@pytest.mark.parametrize('capability', [(7, 5), (8, 0), (9, 0)])
def test_compatibility_mode_suppresses_every_experiment_even_when_requested(capability):
    requested = dict.fromkeys(worker.EXPERIMENTS, True)
    result = worker.effective_options(requested, True, capability)
    assert result['requested'] == requested
    assert not any(result['effective'].values())
    assert set(result['reasons']) == set(worker.EXPERIMENTS)


@pytest.mark.parametrize('capability', [(7, 5), (8, 0)])
def test_actual_gpu_cell_never_calls_optional_installer_in_compatibility_mode(capability):
    _, sources = notebook_sources()
    source = sources[3].split('# Default checkpoint:')[0]
    # Exercise both notebook GPU branches, including an adversarial requested
    # true flag and saved compile Secret. The heavy installer body stays inert.
    for option in worker.EXPERIMENTS:
        if option != 'AUTO_COMPILE':
            source = source.replace(option + ' = False', option + ' = True')
    cuda = types.SimpleNamespace(is_available=lambda: True,
        get_device_capability=lambda _: capability, get_device_name=lambda _: 'Fake GPU',
        get_device_properties=lambda _: types.SimpleNamespace(total_memory=16 * 1024**3))
    torch = types.SimpleNamespace(cuda=cuda)
    namespace = {'__builtins__': __builtins__, 'Path': Path, 'json': json,
        '_worker_setup': vars(worker), 'COMPATIBILITY_MODE': True,
        'PHONE_STUDIO_AUTO_COMPILE': '1', 'run': lambda *a, **k: pytest.fail('optional installer ran')}
    source = source.replace('import torch', '', 1)
    namespace['torch'] = torch
    exec(compile(source, '<gpu-policy-fixture>', 'exec'), namespace)
    assert namespace['PHONE_STUDIO_AUTO_COMPILE'] == '0'
    assert not namespace['SAGE_ATTENTION_AVAILABLE']
    assert not namespace['T4_FLASH_ATTENTION_AVAILABLE']
    assert not any(namespace['WORKER_OPTIONS']['effective'].values())


def test_saved_phone_switch_cannot_enable_extras_and_still_rejects_invalid_values():
    tree = ast.parse((ROOT / 'tools/speed_extras_bridge.py').read_text(encoding='utf-8'))
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                 and n.name in ('_ps_is_edit_graph', '_ps_speed_requested')]
    namespace = {'_PS_COMPATIBILITY_MODE': True}
    exec(compile(ast.Module(body=functions, type_ignores=[]), '<policy>', 'exec'), namespace)
    choose = namespace['_ps_speed_requested']
    graph = {'1': {'class_type': 'EmptyLatentImage'}}
    assert choose({'phone_studio_speed_extras': True}, graph) is False
    assert choose(None, graph) is False
    with pytest.raises(ValueError, match='Boolean'):
        choose({'phone_studio_speed_extras': 'true'}, graph)


def test_bridge_compile_hook_is_blocked_even_with_conflicting_environment():
    _, sources = notebook_sources()
    assignment = next(n for n in ast.parse(sources[5]).body if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == 'BRIDGE_CODE' for t in n.targets))
    bridge = ast.literal_eval(assignment.value)
    guard = next(n for n in ast.parse(bridge).body if isinstance(n, ast.If)
                 and 'PHONE_STUDIO_AUTO_COMPILE' in ast.unparse(n.test))
    fake_os = types.SimpleNamespace(environ={'PHONE_STUDIO_AUTO_COMPILE': '1'})
    # Executing this if would immediately import Comfy's compile helper if the
    # compatibility guard failed; the fake environment needs no Comfy package.
    exec(compile(ast.Module(body=[guard], type_ignores=[]), '<compile-guard>', 'exec'),
         {'os': fake_os, '_PS_COMPATIBILITY_MODE': True})


def test_actual_launch_flags_disable_pinned_comfy_compiler_and_precision_experiments(tmp_path):
    _, sources = notebook_sources()
    cli = tmp_path / 'comfy/cli_args.py'
    cli.parent.mkdir()
    cli.write_text('--disable-comfy-compiler --fp16-intermediates --fp16-vae fp16_accumulation')
    source = sources[6].split('# Use named features:')[1].split("print('Speed settings:")[0]
    namespace = {'RUNTIME_ROOT': tmp_path, 'COMPATIBILITY_MODE': True,
        'FAST_FP16_ACCUMULATION': False, 'FAST_FP16_INTERMEDIATES': False,
        'FAST_FP16_VAE': False, 'CHANNELS_LAST': True, 'VRAM_MODE': 'auto',
        'COMPRESS_JSON_RESPONSES': False}
    # Restore the first comment fragment after slicing the source.
    exec(compile('#' + source, '<launch-flags>', 'exec'), namespace)
    flags = namespace['speed_flags']
    assert '--disable-comfy-compiler' in flags
    assert '--fp16-intermediates' not in flags and '--fp16-vae' not in flags
    assert 'fp16_accumulation' not in flags


@pytest.mark.parametrize('wrong', ['instance', 'runtime', 'not-ready'])
def test_local_open_port_is_not_ready_without_owned_authenticated_instance(wrong):
    health = {'ok': True, 'instanceId': 'owned-instance',
              'workerRuntime': {'runtimeId': 'owned-runtime'}}
    if wrong == 'instance':
        health['instanceId'] = 'other-instance'
    elif wrong == 'runtime':
        health['workerRuntime']['runtimeId'] = 'other-runtime'
    else:
        health['ok'] = False
    with pytest.raises(RuntimeError, match='preserve the other process'):
        worker.confirm_runtime_health(health, 'owned-instance', 'owned-runtime')
    valid = {'ok': True, 'instanceId': 'owned-instance', 'workerRuntime': {'runtimeId': 'owned-runtime'}}
    assert worker.confirm_runtime_health(valid, 'owned-instance', 'owned-runtime') is valid


def test_existing_private_credentials_are_not_overwritten_by_another_workers_secret(tmp_path):
    path = tmp_path / 'credentials.json'
    original = {'phone_studio_token': 'saved-token', 'tunnel_password': 'saved-password'}
    path.write_text(json.dumps(original))
    assert worker.load_credentials(path, 'other-token', 'other-password') == ('other-token', 'other-password')
    assert json.loads(path.read_text()) == original
    assert worker.load_credentials(path) == ('saved-token', 'saved-password')
    assert not list(tmp_path.glob('*.part')) and not list(tmp_path.glob('*.lock'))


def test_unknown_or_malformed_credentials_and_artifact_lock_are_preserved(tmp_path):
    path = tmp_path / 'credentials.json'
    path.write_text('not JSON')
    with pytest.raises(RuntimeError, match='preserve'):
        worker.load_credentials(path)
    assert path.read_text() == 'not JSON'
    lock = tmp_path / 'owned.lock'
    lock.write_text('other-worker')
    with pytest.raises(RuntimeError, match='Another instance'):
        with worker.exclusive_artifact(lock, timeout=0):
            pytest.fail('occupied lock entered')
    assert lock.read_text() == 'other-worker'


def test_auxiliary_staging_does_not_collide_with_same_pid_on_another_vm(tmp_path, monkeypatch):
    payload = b'fake pinned artifact'
    monkeypatch.setattr(editing, 'FOOOCUS_WEIGHTS', {'fake.patch': (len(payload), hashlib.sha256(payload).hexdigest())})
    monkeypatch.setattr(editing.urllib.request, 'urlopen', lambda *a, **k: io.BytesIO(payload))
    other = tmp_path / ('fake.patch.' + str(os.getpid()) + '.part')
    other.write_bytes(b'other-instance-in-progress')
    editing._download_weight('fake.patch', tmp_path, 0)
    assert (tmp_path / 'fake.patch').read_bytes() == payload
    assert other.read_bytes() == b'other-instance-in-progress'
    assert list(tmp_path.glob('*.part')) == [other]


def test_unknown_checkout_never_invokes_clone_pull_or_deletes_user_files(tmp_path, monkeypatch):
    root = tmp_path / 'ComfyUI'
    root.mkdir()
    (root / 'my-file').write_text('keep')
    monkeypatch.setattr(worker, 'run_stage', lambda *a, **k: pytest.fail('unknown checkout mutated'))
    with pytest.raises(RuntimeError, match='Unknown existing'):
        worker.prepare_checkout(root)
    assert (root / 'my-file').read_text() == 'keep'


@pytest.mark.parametrize('revision,changes,unknown', [('old-revision', '', ''),
    (worker.COMFY_REVISION, 'nodes.py', ''), (worker.COMFY_REVISION, '', 'user-modification.py')])
def test_existing_conflicting_checkout_is_preserved(tmp_path, monkeypatch, revision, changes, unknown):
    root = tmp_path / 'ComfyUI'
    (root / '.git').mkdir(parents=True)
    (root / 'my-file').write_text('keep')
    values = {'checkout_identity': revision, 'checkout_origin': worker.COMFY_REPOSITORY,
              'checkout_changes': changes, 'checkout_untracked': unknown}
    monkeypatch.setattr(worker, 'run_stage', lambda command, **kwargs: values[kwargs['stage']])
    with pytest.raises(RuntimeError, match='conflicts'):
        worker.prepare_checkout(root)
    assert (root / 'my-file').read_text() == 'keep'
    assert not (root / worker.CHECKOUT_MARKER).exists()


@pytest.mark.parametrize('unknown_file', ['', 'models/unexpected-file'])
def test_owned_pinned_checkout_with_verified_link_rejoins_without_fetch_or_install(tmp_path, monkeypatch, unknown_file):
    root = tmp_path / 'ComfyUI'
    (root / '.git').mkdir(parents=True)
    target = tmp_path / 'shared-models'
    target.mkdir()
    try:
        (root / 'models').symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip('Platform does not permit local symlink fixture; live Linux rejoin still pending.')
    record = {'revision': worker.COMFY_REVISION, 'links': {'models': str(target)}}
    (root / worker.CHECKOUT_MARKER).write_text(json.dumps(record))
    requirements = b'fake pinned requirements'
    (root / 'requirements.txt').write_bytes(requirements)
    monkeypatch.setattr(worker, 'COMFY_REQUIREMENTS_SHA256', hashlib.sha256(requirements).hexdigest())
    values = {'checkout_identity': worker.COMFY_REVISION, 'checkout_origin': worker.COMFY_REPOSITORY,
              'checkout_changes': 'models/README.md',
              'checkout_untracked': worker.CHECKOUT_MARKER + '\nmodels\n' + unknown_file}
    stages = []
    def run(command, **kwargs):
        stages.append(kwargs['stage'])
        return values[kwargs['stage']]
    monkeypatch.setattr(worker, 'run_stage', run)
    if unknown_file:
        with pytest.raises(RuntimeError, match='conflicts'):
            worker.prepare_checkout(root)
    else:
        assert worker.prepare_checkout(root) == worker.COMFY_REVISION
        assert worker.prepare_checkout(root) == worker.COMFY_REVISION
    assert set(stages) == set(values)
    assert (root / 'models').resolve() == target


def test_dependency_resolution_rejects_any_torch_or_cuda_replacement():
    for name in ('torch', 'torchvision', 'torchaudio', 'triton', 'nvidia-cublas-cu12'):
        with pytest.raises(RuntimeError, match='protected GPU'):
            worker.validate_dependency_report({'install': [{'metadata': {'name': name}}]}, {})
    worker.validate_dependency_report({'install': [{'metadata': {'name': 'aiohttp'}}]}, {})


@pytest.mark.parametrize('replace_gpu', [True, False])
def test_dependency_dry_run_precedes_install_with_exact_gpu_identity(tmp_path, monkeypatch, replace_gpu):
    stack = {'packages': {'torch': '2.9.0+cu129', 'torchvision': '0.24.0+cu129',
                         'torchaudio': '2.9.0+cu129'}, 'torchCuda': '12.9', 'cudaAvailable': True}
    monkeypatch.setattr(worker, 'torch_stack', lambda *a: stack)
    stages = []
    def run(command, **kwargs):
        stages.append((kwargs['stage'], command, kwargs['timeout']))
        if kwargs['stage'] == 'dependency_preflight':
            report = {'install': [{'metadata': {'name': 'torch'}}]} if replace_gpu else {'install': []}
            Path(command[command.index('--report') + 1]).write_text(json.dumps(report))
        return ''
    monkeypatch.setattr(worker, 'run_stage', run)
    if replace_gpu:
        with pytest.raises(RuntimeError, match='protected GPU'):
            worker.install_dependencies(tmp_path, log_root=tmp_path / 'logs')
        assert [s[0] for s in stages] == ['dependency_preflight']
    else:
        assert worker.install_dependencies(tmp_path, log_root=tmp_path / 'logs') == stack
        assert [s[0] for s in stages] == ['dependency_preflight', 'dependency_install', 'dependency_imports']
    assert '--only-binary=:all:' in stages[0][1]
    assert '--dry-run' in stages[0][1]
    assert 'torch==2.9.0+cu129' in (tmp_path / 'logs/existing-gpu-stack.txt').read_text()
    assert all(0 < s[2] <= 600 for s in stages)


def test_setup_stage_timeout_retains_redacted_bounded_diagnostics(tmp_path, monkeypatch):
    def timeout(*a, **k):
        raise subprocess.TimeoutExpired('ignored', 1, output='password=secret https://private.invalid/?token=bad')
    monkeypatch.setattr(worker.subprocess, 'run', timeout)
    with pytest.raises(RuntimeError, match='deadline exceeded'):
        worker.run_stage(['safe'], stage='test_stage', log_root=tmp_path, timeout=1)
    text = next(tmp_path.glob('test_stage.*.log')).read_text()
    assert 'deadline' in text and 'secret' not in text and 'private.invalid' not in text


def test_final_notebook_is_cleared_and_matches_helpers_and_hashes():
    notebook, sources = notebook_sources()
    assert len({c['id'] for c in notebook['cells']}) == len(notebook['cells'])
    literals = {}
    for cell, source in zip(notebook['cells'], sources):
        if cell['cell_type'] != 'code':
            continue
        assert cell['execution_count'] is None and not cell['outputs']
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        literals[target.id] = node.value.value
    assert literals['WORKER_RUNTIME_SETUP_CODE'].strip() == (ROOT / 'tools/worker_runtime_setup.py').read_text(encoding='utf-8').strip()
    assert literals['EDIT_WORKER_SETUP_CODE'].strip() == (ROOT / 'tools/edit_worker_setup.py').read_text(encoding='utf-8').strip()
    assert literals['T4_FLASH_INSTALLER_CODE'].strip() == (ROOT / 'tools/t4_flash_attention_install.py').read_text(encoding='utf-8').strip()
    assert (ROOT / 'tools/speed_extras_bridge.py').read_text(encoding='utf-8').strip() in literals['BRIDGE_CODE']
    for name, digest in notebook['metadata']['phone_studio_recovery']['embedded_source_sha256'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
    assert literals['COMPATIBILITY_MODE'] is True
    assert literals['DEFAULT_CHECKPOINT'] == 'waiIllustriousSDXL_v170.safetensors'
    assert 'git\', \'pull' not in sources[2]
    assert 'workerRuntime' in literals['BRIDGE_CODE']
