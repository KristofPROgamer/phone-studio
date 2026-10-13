"""Verify delivered command entry points without connecting or running setup."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_acceptance_help_works_outside_project_without_pythonpath(tmp_path):
    result = subprocess.run([sys.executable, "-I", str(ROOT / "tools/llm_acceptance.py"), "--help"],
                            cwd=tmp_path, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert "--four-image-only" in result.stdout
    assert "--report" in result.stdout


def test_setup_file_import_works_outside_project_without_starting_setup(tmp_path):
    script = "import runpy,sys; m=runpy.run_path(sys.argv[1]); print(m['MODEL_REPO'])"
    result = subprocess.run([sys.executable, "-I", "-c", script, str(ROOT / "tools/router_setup.py")],
                            cwd=tmp_path, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert "Huihui-Qwen3.5-4B-abliterated-GGUF" in result.stdout
