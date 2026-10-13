"""CPU fixtures for effective RAM accounting, no host/GPU runtime claims."""
from pathlib import Path
from unittest.mock import patch
import json
import tempfile
import unittest

from tools import runtime_diagnostics as diagnostics
from tools import llm_acceptance as acceptance


def cgroup_fixture(tmp_path, monkeypatch, leaf_limit, leaf_current):
    root = tmp_path / 'cgroup'
    values = {str(Path('/proc/self/cgroup')): '0::/parent/leaf\n'}
    for path, maximum, current in ((root, 'max', 950), (root / 'parent', 1000, 900),
                                    (root / 'parent/leaf', leaf_limit, leaf_current)):
        for name, value in (('memory.max', maximum), ('memory.current', current),
                            ('memory.peak', current), ('memory.events', 'oom 3\noom_kill 2\n')):
            values[str(path / name)] = str(value)
    monkeypatch.setattr(diagnostics, '_read', lambda path: values.get(str(Path(path))))
    return diagnostics._cgroup(root)


def test_unlimited_leaf_obeys_tighter_parent_and_sibling_headroom(tmp_path, monkeypatch):
    group = cgroup_fixture(tmp_path, monkeypatch, 'max', 100)
    assert group['effectiveLimitVerified'] is True
    assert group['effectiveLimitBytes'] == 1000
    assert group['effectiveHeadroomBytes'] == 100
    assert group['ancestors'][0]['memory.events']['oom_kill'] == 2
    monkeypatch.setattr(diagnostics, '_cgroup', lambda: group)
    monkeypatch.setattr(diagnostics, '_memory_fields', lambda *args: {'MemAvailable': 5000})
    assert diagnostics.available_memory() == 100


def test_tighter_leaf_limit_still_obeys_parent_usage(tmp_path, monkeypatch):
    group = cgroup_fixture(tmp_path, monkeypatch, 500, 200)
    assert group['effectiveLimitBytes'] == 500
    assert group['effectiveHeadroomBytes'] == 100


def test_unavailable_effective_bound_cannot_authorize_cpu_retry(tmp_path, monkeypatch):
    group = cgroup_fixture(tmp_path, monkeypatch, 'unavailable', 100)
    assert group['effectiveLimitVerified'] is False
    monkeypatch.setattr(diagnostics, '_cgroup', lambda: group)
    monkeypatch.setattr(diagnostics, '_memory_fields', lambda *args: {'MemAvailable': 5000})
    assert diagnostics.available_memory() == 0


class FailedAcceptanceClient:
    closed = False

    def __init__(self, *args, **kwargs):
        self.model_id, self.revision = 'fixture', 'fixture'
        self._last_inference = None

    async def enhance(self, request):
        self._last_inference = {'status': 'failed', 'category': 'context_overflow',
            'httpStatus': 400, 'serverType': 'exceed_context_size_error', 'inferenceMillis': 12}
        return {'status': 'unavailable', 'warnings': ['Input exceeded the context budget.']}

    async def plan_edit(self, request, path):
        raise AssertionError('Failed-first smoke must stop before its image call.')

    async def close(self):
        type(self).closed = True


class AcceptanceDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_returned_failure_saves_adapter_category_and_status_before_logging_setup(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'smoke.json'
            with patch.object(acceptance, 'LLMClient', FailedAcceptanceClient), \
                 patch.object(acceptance, 'snapshot', return_value={'hostMemoryBytes': None, 'gpu': None}):
                with self.assertRaisesRegex(RuntimeError, 'acceptance failed'):
                    await acceptance.run_checks(target)
            report = json.loads(target.read_text())
            self.assertFalse(report['passed'])
            self.assertEqual(len(report['cases']), 1)
            evidence = report['cases'][0]['lastInference']
            self.assertEqual(evidence['category'], 'context_overflow')
            self.assertEqual(evidence['httpStatus'], 400)
            self.assertEqual(evidence['inferenceMillis'], 12)
            self.assertTrue(FailedAcceptanceClient.closed)
