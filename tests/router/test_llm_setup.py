"""Tiny setup fixtures only: no model downloads, inference, CUDA or builds."""
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

from router.config import Config
from router.model_profile import (MODEL_REPO, MODEL_REVISION, PRIMARY_PROFILE,
                                  QUALITY_FALLBACK_PROFILE, SERVER_SETTINGS, get_profile)
from tools.router_setup import (ARTIFACTS, PREBUILT_RELEASE, SetupError,
    _exclusive_lock, _existing_session, _fingerprint, _manifest, _prebuilt_download,
    _prebuilt_extract, _server_ready, _session_identity, _stop, download_verified, gpu_info,
    prepare_prebuilt, setup_runtime, start_server)

GIB = 1024**3
DISK = type('Disk', (), {'free': 30 * GIB})()
GPU = {'name': 'Tesla T4', 'architecture': 75, 'freeMiB': 15000}


def tar_fixture(path, files):
    with tarfile.open(path, 'w:gz') as archive:
        for name, content in files.items():
            item = tarfile.TarInfo(name)
            item.size, item.mode = len(content), 0o755
            archive.addfile(item, io.BytesIO(content))
    return {'name': path.name, 'size': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def prebuilt_fixture(root):
    return (
        tar_fixture(root / 'server.tar.gz', {'llama-b11146/llama-server': b'fixture server',
                     'llama-b11146/libggml.so': b'fixture library'}),
        tar_fixture(root / 'runtime.tar.gz', {
            'cudart-llama-b11146-bin-ubuntu-cuda-12.8-x64/' + name: b'fixture cuda'
            for name in ('libcudart.so.12', 'libcublas.so.12', 'libcublasLt.so.12')}),
    )


def prebuilt_patches(artifacts, responses):
    stack = ExitStack()
    stack.enter_context(patch('tools.router_setup.platform.system', return_value='Linux'))
    stack.enter_context(patch('tools.router_setup.platform.machine', return_value='x86_64'))
    stack.enter_context(patch('tools.router_setup.platform.libc_ver', return_value=('glibc', '2.39')))
    stack.enter_context(patch('tools.router_setup.shutil.disk_usage', return_value=DISK))
    stack.enter_context(patch('tools.router_setup.PREBUILT_ARTIFACTS', artifacts))
    stack.enter_context(patch('tools.router_setup.subprocess.run', side_effect=responses))
    return stack


def valid_probes():
    return [subprocess.CompletedProcess([], 0, stdout='version 7fe450e', stderr=''),
            subprocess.CompletedProcess([], 0, stdout='', stderr='CUDA0: Tesla T4')]


class LLMSetupTests(unittest.TestCase):
    def test_primary_identity_and_single_conditional_fallback(self):
        self.assertEqual(sum(item['size'] for item in ARTIFACTS), 3379938240)
        self.assertEqual(Config.llm_model, MODEL_REPO)
        self.assertEqual(Config.llm_revision, MODEL_REVISION)
        self.assertEqual(get_profile(), PRIMARY_PROFILE)
        with self.assertRaises(ValueError):
            get_profile('9b')
        self.assertEqual(get_profile('9b', quality_fallback_confirmed=True), QUALITY_FALLBACK_PROFILE)
        self.assertTrue(all(len(item['sha256']) == 64 for item in ARTIFACTS))

    def test_t4_profile_estimate_and_occupied_gpu_guard(self):
        with patch('tools.router_setup._run', return_value='Tesla T4, 7.5, 15360, 9000'):
            self.assertEqual(gpu_info()['architecture'], 75)
        with patch('tools.router_setup._run', return_value='Tesla T4, 7.5, 15360, 4000'):
            with self.assertRaisesRegex(SetupError, 'provisional.*VRAM'):
                gpu_info()
        with patch('tools.router_setup._run', return_value='older, 6.1, 16000, 15000'):
            with self.assertRaisesRegex(SetupError, 'SM75'):
                gpu_info()

    def test_gpu_missing_driver_has_distinct_real_log(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch('tools.router_setup._run', side_effect=SetupError('nvidia-smi missing')):
            log = Path(directory) / 'probe.log'
            with self.assertRaisesRegex(SetupError, 'GPU visibility/driver'):
                gpu_info(log=log)
            self.assertIn('gpu visibility', log.read_text())

    def test_verified_tiny_download_is_atomic_and_reused(self):
        content = b'tiny mocked gguf file'
        artifact = {'name': 'fixture.gguf', 'size': len(content),
                    'sha256': hashlib.sha256(content).hexdigest()}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch('tools.router_setup.shutil.disk_usage', return_value=DISK), \
                 patch('tools.router_setup.urllib.request.urlopen', return_value=io.BytesIO(content)) as network:
                result = download_verified(root, artifact)
                self.assertEqual(result.read_bytes(), content)
                self.assertFalse(list(root.glob('*.download*')))
                download_verified(root, artifact)
                self.assertEqual(network.call_count, 1)
                self.assertIn(MODEL_REVISION, network.call_args.args[0].full_url)

    def test_mismatched_download_never_promoted(self):
        artifact = {'name': 'fixture.gguf', 'size': 4, 'sha256': '0' * 64}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch('tools.router_setup.shutil.disk_usage', return_value=DISK), \
                 patch('tools.router_setup.urllib.request.urlopen', return_value=io.BytesIO(b'oops')):
                with self.assertRaises(SetupError):
                    download_verified(root, artifact)
                self.assertFalse(list(root.glob('fixture.gguf*')))

    def test_cache_path_cannot_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(SetupError):
                download_verified(Path(directory), {'name': '../escape.gguf', 'size': 1, 'sha256': '0' * 64})

    def test_rerun_reuses_before_fresh_gpu_memory_guard(self):
        existing = {'environment': {}, 'process': None, 'pid': 99, 'reused': True}
        with tempfile.TemporaryDirectory() as directory, \
             patch('tools.router_setup._existing_session', return_value=existing), \
             patch('tools.router_setup.gpu_info') as probe:
            self.assertIs(setup_runtime(runtime_dir=directory), existing)
            probe.assert_not_called()

    def test_failed_prebuilt_never_uses_source_or_downloads_weights(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch('tools.router_setup.gpu_info', return_value=GPU), \
             patch('tools.router_setup.shutil.disk_usage', return_value=DISK), \
             patch('tools.router_setup.prepare_prebuilt', side_effect=SetupError('loader failed')), \
             patch('tools.router_setup.build_server') as build, \
             patch('tools.router_setup.download_verified') as download:
            with self.assertRaisesRegex(SetupError, 'No source compilation'):
                setup_runtime(runtime_dir=directory, cache_dir=directory)
            build.assert_not_called()
            download.assert_not_called()

    def test_small_lock_preserves_other_owner_and_cleans_own(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with _exclusive_lock(root, 'fixture.lock'):
                owner = (root / 'fixture.lock').read_bytes()
                with self.assertRaisesRegex(SetupError, 'locked'):
                    with _exclusive_lock(root, 'fixture.lock'):
                        self.fail('Concurrent owner entered')
                self.assertEqual((root / 'fixture.lock').read_bytes(), owner)
            self.assertFalse((root / 'fixture.lock').exists())

    def test_prebuilt_probe_failure_does_not_poison_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = prebuilt_fixture(root)
            failure = subprocess.CalledProcessError(127, [], output='', stderr='libmissing.so not found')
            with prebuilt_patches(artifacts, [failure] + valid_probes()):
                with self.assertRaisesRegex(SetupError, 'staging failed'):
                    prepare_prebuilt(root)
                self.assertFalse((root / PREBUILT_RELEASE).exists())
                self.assertFalse(list(root.glob('prebuilt-stage-*')))
                self.assertTrue((root / 'server.tar.gz').exists())
                self.assertIn('libmissing.so', (root / 'setup-probes.log').read_text())
                result = prepare_prebuilt(root)
                self.assertTrue(Path(result['binary']).is_file())
                stamp = json.loads((root / PREBUILT_RELEASE / 'verified-prebuilt.json').read_text())
                self.assertTrue(any(f['path'] == 'libcublas.so.12' for f in stamp['files']))
                self.assertFalse((root / '.prebuilt-setup.lock').exists())

    def test_prebuilt_corrupt_library_is_rejected_and_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = prebuilt_fixture(root)
            with prebuilt_patches(artifacts, valid_probes()):
                result = prepare_prebuilt(root)
            library = Path(result['libraryPath']) / 'libggml.so'
            library.write_bytes(b'corrupt')
            with prebuilt_patches(artifacts, []):
                with self.assertRaisesRegex(SetupError, 'changed prebuilt directory preserved'):
                    prepare_prebuilt(root)
            self.assertEqual(library.read_bytes(), b'corrupt')

    def test_unknown_prebuilt_directory_is_preserved_without_download(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / PREBUILT_RELEASE).mkdir()
            marker = root / PREBUILT_RELEASE / 'user-file'
            marker.write_text('preserve')
            with prebuilt_patches((), []), patch('tools.router_setup._prebuilt_download') as download:
                with self.assertRaisesRegex(SetupError, 'directory preserved'):
                    prepare_prebuilt(root)
                download.assert_not_called()
            self.assertEqual(marker.read_text(), 'preserve')

    def test_probe_timeout_writes_stage_timeout_log(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = prebuilt_fixture(root)
            with prebuilt_patches(artifacts, [subprocess.TimeoutExpired([], 45, stderr=b'driver hung')]):
                with self.assertRaises(SetupError):
                    prepare_prebuilt(root)
            log = (root / 'setup-probes.log').read_text()
            self.assertIn('driver hung', log)
            self.assertIn('"timeout": true', log)
            self.assertFalse((root / PREBUILT_RELEASE).exists())

    def test_archive_hash_rejected_without_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            corrupt = root / 'bad.tar.gz'
            corrupt.write_bytes(b'bad')
            with self.assertRaisesRegex(RuntimeError, 'failed verification'):
                _prebuilt_download(root, {'name': corrupt.name, 'size': 3, 'sha256': '0' * 64})
            self.assertEqual(corrupt.read_bytes(), b'bad')

    def test_extraction_rejects_escaping_archive_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tar_fixture(root / 'unsafe.tar.gz', {'../escape': b'bad'})
            destination = root / 'stage'
            destination.mkdir()
            with self.assertRaisesRegex(RuntimeError, 'Unsafe'):
                _prebuilt_extract(root / 'unsafe.tar.gz', destination)
            self.assertFalse((root / 'escape').exists())

    def test_extraction_rejects_external_symlinks_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / 'unsafe-link.tar.gz'
            with tarfile.open(archive_path, 'w:gz') as archive:
                link = tarfile.TarInfo('lib.so')
                link.type, link.linkname = tarfile.SYMTYPE, '../outside.so'
                archive.addfile(link)
            destination = root / 'stage'
            destination.mkdir()
            with self.assertRaisesRegex(RuntimeError, 'Unsafe prebuilt library symlink'):
                _prebuilt_extract(archive_path, destination)
            self.assertEqual(list(destination.iterdir()), [])

    def test_server_readiness_requires_real_alias_and_vision_contract(self):
        def reply(value):
            return io.BytesIO(json.dumps(value).encode())
        opener = MagicMock()
        with patch('tools.router_setup.urllib.request.build_opener', return_value=opener):
            opener.open.side_effect = [reply({'status': 'ok'}), reply({'modalities': {'vision': True}}),
                                      reply({'data': [{'id': MODEL_REPO}]})]
            self.assertTrue(_server_ready(8081, 'private-key'))
            opener.open.side_effect = [reply({'status': 'ok'}), reply({'modalities': {'vision': True}}),
                                      reply({'data': [{'id': 'old-27b-model'}]})]
            self.assertFalse(_server_ready(8081, 'private-key'))
            opener.open.side_effect = [reply({'status': 'ok'}), reply({'modalities': {'vision': False}})]
            self.assertFalse(_server_ready(8081, 'private-key'))

    def test_manifest_records_symlink_identity_and_target_integrity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'lib.so.1').write_bytes(b'library')
            try:
                (root / 'lib.so').symlink_to('lib.so.1')
            except OSError as exc:
                self.skipTest(f'Local Windows symlink privilege unavailable: {exc}')
            manifest = _manifest(root)
            self.assertIn({'path': 'lib.so', 'kind': 'symlink', 'target': 'lib.so.1'}, manifest)
            self.assertTrue(any(f['path'] == 'lib.so.1' and 'sha256' in f for f in manifest))

    def _start_patches(self, directory, ready=True):
        root = Path(directory)
        binary = root / 'mock-binary'
        binary.write_bytes(b'fake native binary')
        process = MagicMock()
        process.poll.return_value = None
        process.pid = 99
        stack = ExitStack()
        stack.enter_context(patch('socket.socket'))
        stack.enter_context(patch('tools.router_setup._server_ready',
            side_effect=ready if isinstance(ready, list) else None,
            return_value=ready if not isinstance(ready, list) else None))
        stack.enter_context(patch('tools.router_setup._process_start', return_value='fixture-start'))
        popen = stack.enter_context(patch('tools.router_setup.subprocess.Popen', return_value=process))
        stop = stack.enter_context(patch('tools.router_setup._stop'))
        return stack, binary, process, popen, stop

    def test_native_process_is_private_and_serving_policy_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            stack, binary, _, popen, stop = self._start_patches(directory)
            with stack, patch.dict('os.environ', {'PHONE_STUDIO_WORKERS_JSON': 'private-workers',
                    'NGROK_AUTHTOKEN': 'private-tunnel', 'LLAMA_ARG_TOOLS': 'all', 'LLAMA_ARG_CTX_SIZE': 'wrong'}):
                result = start_server(binary, Path('mock-weights'), Path('mock-projector'), Path(directory))
            self.assertFalse(result['reused'])
            command = popen.call_args.args[0]
            environment = popen.call_args.kwargs['env']
            self.assertIn('--no-agent', command)
            self.assertIn('--no-webui-mcp-proxy', command)
            for flag, value in (('--host', '127.0.0.1'), ('--ctx-size', '8192'),
                    ('--parallel', '1'), ('--batch-size', '256'), ('--ubatch-size', '128')):
                self.assertEqual(command[command.index(flag) + 1], value)
            self.assertNotIn('--no-mmproj-offload', command)
            for name in ('PHONE_STUDIO_WORKERS_JSON', 'NGROK_AUTHTOKEN', 'LLAMA_ARG_TOOLS', 'LLAMA_ARG_CTX_SIZE'):
                self.assertNotIn(name, environment)
            stop.assert_not_called()
            self.assertTrue(result['fingerprint'])

    def test_matching_owned_session_reuse_and_mismatch_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            stack, binary, _, _, _ = self._start_patches(directory)
            with stack:
                fresh = start_server(binary, Path('weights'), Path('projector'), Path(directory), gpu=GPU)
                reused = _existing_session(Path(directory), 8081, server_source='explicit source build')
                self.assertTrue(reused['reused'])
                for name in ('fingerprint', 'artifacts', 'profile', 'serverSource', 'gpu', 'placementEvidence'):
                    self.assertEqual(fresh[name], reused[name])
                self.assertIsNone(_existing_session(Path(directory), 8081,
                    profile=QUALITY_FALLBACK_PROFILE, server_source='explicit source build'))
                with patch.dict(SERVER_SETTINGS, {'context': 4096}):
                    self.assertIsNone(_existing_session(Path(directory), 8081, server_source='explicit source build'))
                binary.write_bytes(b'changed native binary')
                self.assertIsNone(_existing_session(Path(directory), 8081, server_source='explicit source build'))

    def test_prebuilt_session_reuse_checks_library_integrity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = prebuilt_fixture(root)
            with prebuilt_patches(artifacts, valid_probes()):
                prebuilt = prepare_prebuilt(root)
            runtime = root / 'runtime'
            runtime.mkdir()
            stack, _, _, _, _ = self._start_patches(runtime)
            stack.enter_context(patch('tools.router_setup.PREBUILT_ARTIFACTS', artifacts))
            with stack:
                fresh = start_server(Path(prebuilt['binary']), Path('weights'), Path('projector'),
                    runtime, server_info=prebuilt, native_library_path=prebuilt['libraryPath'])
                reused = _existing_session(runtime, 8081)
                self.assertTrue(reused['reused'])
                self.assertEqual(fresh['serverInfo'], reused['serverInfo'])
                (Path(prebuilt['libraryPath']) / 'libggml.so').write_bytes(b'changed')
                self.assertIsNone(_existing_session(runtime, 8081))

    def test_reuse_rejects_adapter_url_key_and_degraded_environment_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stack, binary, _, _, _ = self._start_patches(directory)
            with stack:
                start_server(binary, Path('weights'), Path('projector'), root)
                path = root / 'llm-session.json'
                original = json.loads(path.read_text())
                before = dict(os.environ)
                for name, wrong in (
                    ('PHONE_STUDIO_LLM_URL', 'http://127.0.0.1:9999'),
                    ('PHONE_STUDIO_LLM_API_KEY', 'wrong-private-key'),
                    ('PHONE_STUDIO_LLM_DEGRADED', 'incorrect placement')):
                    damaged = json.loads(json.dumps(original))
                    damaged['environment'][name] = wrong
                    path.write_text(json.dumps(damaged))
                    self.assertIsNone(_existing_session(root, 8081, server_source='explicit source build'))
                    self.assertEqual(dict(os.environ), before)
                path.write_text(json.dumps(original))
                self.assertTrue(_existing_session(root, 8081, server_source='explicit source build')['reused'])

    def test_session_projector_hash_is_part_of_identity(self):
        original = _fingerprint(_session_identity(PRIMARY_PROFILE, 8081, 'prebuilt', False))
        changed = dict(PRIMARY_PROFILE, artifacts=[dict(a) for a in ARTIFACTS])
        changed['artifacts'][1]['sha256'] = '0' * 64
        self.assertNotEqual(original, _fingerprint(_session_identity(changed, 8081, 'prebuilt', False)))

    def test_startup_interrupt_cleans_only_owned_process_and_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            stack, binary, process, popen, stop = self._start_patches(directory, ready=[KeyboardInterrupt()])
            with stack:
                with self.assertRaises(KeyboardInterrupt):
                    start_server(binary, Path('weights'), Path('projector'), Path(directory))
                stop.assert_called_once_with(process)
                self.assertEqual(popen.call_count, 1)
            self.assertFalse((Path(directory) / 'llm-session.json').exists())
            self.assertFalse((Path(directory) / '.llm-startup.lock').exists())

    def test_timeout_cleans_owned_process_without_automatic_cpu_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            stack, binary, process, popen, stop = self._start_patches(directory, ready=False)
            with stack, patch('tools.router_setup.time.monotonic', side_effect=[0, 2]):
                with self.assertRaisesRegex(SetupError, 'startup_timeout'):
                    start_server(binary, Path('weights'), Path('projector'), Path(directory), startup_timeout=1)
                stop.assert_called_once_with(process)
                self.assertEqual(popen.call_count, 1)
            self.assertFalse((Path(directory) / 'llm-session.json').exists())

    def test_invalid_cli_does_not_retry_even_with_explicit_cpu_option(self):
        with tempfile.TemporaryDirectory() as directory:
            stack, binary, process, popen, stop = self._start_patches(directory, ready=False)
            process.poll.return_value = 2
            def fake_spawn(*args, **kwargs):
                (Path(directory) / 'llama-server.log').write_text('error: unknown argument --fixture')
                return process
            popen.side_effect = fake_spawn
            with stack:
                with self.assertRaisesRegex(SetupError, 'invalid_cli'):
                    start_server(binary, Path('weights'), Path('projector'), Path(directory), cpu_projector_fallback=True)
                self.assertEqual(popen.call_count, 1)
                stop.assert_called_once_with(process)

    def test_launch_error_retains_real_stage_log_without_cpu_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            stack, binary, _, popen, stop = self._start_patches(directory)
            popen.side_effect = OSError('fixture missing loader')
            with stack:
                with self.assertRaisesRegex(SetupError, 'launch/session publication failed'):
                    start_server(binary, Path('weights'), Path('projector'), Path(directory), cpu_projector_fallback=True)
                self.assertEqual(popen.call_count, 1)
                stop.assert_not_called()
            self.assertIn('fixture missing loader', (Path(directory) / 'setup-startup.log').read_text())

    def test_unrelated_port_owner_is_not_stopped_or_authenticated(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch('socket.socket') as socket, \
             patch('tools.router_setup._server_ready') as ready, \
             patch('tools.router_setup._stop') as stop, \
             patch('tools.router_setup.subprocess.Popen') as popen:
            socket.return_value.__enter__.return_value.bind.side_effect = OSError('occupied')
            with self.assertRaisesRegex(SetupError, 'No existing process was stopped'):
                start_server(Path('binary'), Path('weights'), Path('projector'), Path(directory))
            ready.assert_not_called()
            stop.assert_not_called()
            popen.assert_not_called()

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Linux owned-process-group cleanup cannot run on this Windows host.')
    def test_owned_process_group_cleanup_reaps_linux_parent(self):
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'], start_new_session=True)
        try:
            self.assertEqual(os.getpgid(process.pid), process.pid)
            _stop(process)
            self.assertIsNotNone(process.poll())
        finally:
            if process.poll() is None:
                os.killpg(process.pid, 9)
                process.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
