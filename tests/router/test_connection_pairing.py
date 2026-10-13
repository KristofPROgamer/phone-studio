"""CPU-only private-code and credential fixtures; no tunnel or phone claims."""
import base64
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import types
from unittest.mock import patch

import pytest

from tools import connection_pairing as pairing


def payload(kind="router", **changes):
    result = {"version": 1, "kind": kind, "name": "Phone Studio router",
              "serverUrl": "https://router.example", "tunnelUser": "studio",
              "tunnelPassword": "private-password", "studioToken": "private-token"}
    if kind == "worker":
        result.update(workerId="worker-1", name="Worker 1", serverUrl="https://worker1.example")
    return result | changes


def raw_code(text):
    return pairing.PREFIX + base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


@pytest.mark.parametrize("kind", ["router", "worker"])
def test_roundtrip_preserves_credentials_and_normalizes_clean_address(kind):
    source = payload(kind, tunnelPassword=" pw:é= space ", studioToken="opaque token",
                     serverUrl="https://ROUTER.example:443/base%20path/")
    actual = pairing.decode_pairing(" \n" + pairing.encode_pairing(source) + "\n ", expected_kind=kind)
    assert actual == source | {"serverUrl": "https://router.example/base%20path"}
    assert "private-password" not in pairing.encode_pairing(source)


@pytest.mark.parametrize("count", [1, 2, 3])
def test_multiline_worker_codes_keep_ids_and_credentials(count):
    workers = [payload("worker", workerId=f"worker-{n}", name=f"Worker {n}",
                       serverUrl=f"https://worker{n}.example") for n in range(1, count + 1)]
    result = pairing.workers_from_codes("\n\n" + "\n".join(pairing.encode_pairing(item) for item in workers))
    assert result == [{k: v for k, v in item.items() if k not in ("version", "kind")} for item in workers]
    assert "version" not in json.dumps(result)


@pytest.mark.parametrize("changes", [
    {"version": True}, {"version": 2}, {"kind": "phone"}, {"unexpected": "secret-input"},
    {"name": " "}, {"name": " padded"}, {"name": "x" * 81}, {"studioToken": ""},
    {"tunnelPassword": "\nsecret-input"}, {"tunnelUser": "user:invalid"},
    {"studioToken": "x" * 513}, {"name": "\ud800"}, {"workerId": "invalid-for-router"},
])
def test_invalid_fields_are_redacted(changes):
    with pytest.raises(pairing.PairingError) as error:
        pairing.encode_pairing(payload(**changes))
    assert "secret-input" not in str(error.value)
    assert "private-password" not in str(error.value)


@pytest.mark.parametrize("url", [
    "http://router.example", "HTTPS://router.example", "https://user:secret-input@router.example", "https://router.example?key=secret-input",
    "https://router.example#secret-input", "https://router.example?", "https://router.example#",
    "https://router.example:0", "https://router.example:", "https://bad_host.example", "https://-bad.example", "https://router.example..",
    "https://router.example/../private", "https://router.example/%2e%2e/private", "https://router.example/%0a",
    "https://router.example/%xx", "https://router.example/%FF", "https://router.example\\path", "https://router.example/raw space",
])
def test_invalid_addresses_fail_without_echoing_secrets(url):
    with pytest.raises(pairing.PairingError) as error:
        pairing.encode_pairing(payload(serverUrl=url))
    assert "secret-input" not in str(error.value)


@pytest.mark.parametrize("code", [
    "", "https://public-qr.example", pairing.PREFIX + "bad=", pairing.PREFIX + "a",
    pairing.PREFIX + "e31",  # Noncanonical Base64 pad bits.
    raw_code('{"version":1,"version":1}'), raw_code('{"version":NaN}'), raw_code('[]'),
    raw_code(json.dumps(payload() | {"studioToken": {"secret": "nested"}})),
    pairing.PREFIX + "x" * pairing.MAX_CODE_LENGTH,
    pairing.PREFIX + base64.urlsafe_b64encode(b"x" * (pairing.MAX_PAYLOAD_BYTES + 1)).decode().rstrip("="),
    pairing.PREFIX + base64.urlsafe_b64encode(b"\xff").decode().rstrip("="),
    raw_code("[" * 1600 + "]" * 1600),
])
def test_invalid_encoding_json_and_bounds(code):
    with pytest.raises(pairing.PairingError):
        pairing.decode_pairing(code)


def test_role_worker_identity_and_duplicate_validation():
    router = pairing.encode_pairing(payload())
    worker = pairing.encode_pairing(payload("worker"))
    with pytest.raises(pairing.PairingError):
        pairing.decode_pairing(worker, expected_kind="router")
    for text in (router, worker + "\n" + worker, "\n".join([worker] * 4), ""):
        with pytest.raises(pairing.PairingError):
            pairing.workers_from_codes(text)
    duplicate_address = pairing.encode_pairing(payload("worker", workerId="worker-2", serverUrl="https://WORKER1.example:443/"))
    with pytest.raises(pairing.PairingError):
        pairing.workers_from_codes(worker + "\n" + duplicate_address)
    for identifier in ("", "../worker", "worker space", "a" * 129):
        with pytest.raises(pairing.PairingError):
            pairing.encode_pairing(payload("worker", workerId=identifier))
    invalid = payload("worker")
    del invalid["workerId"]
    with pytest.raises(pairing.PairingError):
        pairing.encode_pairing(invalid)


def test_ipv6_and_trailing_dns_dot_normalization():
    assert pairing.clean_server_url("https://[::1]:443/base/") == "https://[::1]/base"
    assert pairing.clean_server_url("https://Router.example./") == "https://router.example"


def test_html_escapes_labels_and_keeps_code_in_private_details():
    source = payload(name="<script>display</script>")
    page = pairing.pairing_html(source, with_qr=False)
    assert "<script>display</script>" not in page
    assert "&lt;script&gt;display&lt;/script&gt;" in page
    assert "private-password" not in page and "private-token" not in page
    assert "<details>" in page and pairing.encode_pairing(source) in page
    assert page.index("<details>") < page.index(pairing.encode_pairing(source))
    with patch.dict(sys.modules, {"qrcode": None}):
        assert "QR preview is unavailable" in pairing.pairing_html(source)
    assert "https://api.qrserver" not in page


def test_credentials_are_persistent_and_secret_overrides_do_not_rewrite(tmp_path):
    path = tmp_path / "state" / ".phone_studio_router_credentials.json"
    initial = pairing.load_router_credentials(path)
    assert all(len(value) >= 32 for value in initial)
    original = path.read_bytes()
    assert pairing.load_router_credentials(path) == initial
    assert pairing.load_router_credentials(path, "existing-token", "existing-password") == ("existing-token", "existing-password")
    assert path.read_bytes() == original
    assert pairing.load_router_credentials(path) == initial
    assert not list(path.parent.glob("*.part"))
    assert not path.with_name(path.name + ".lock").exists()


def test_initial_supplied_credentials_are_preserved_exactly(tmp_path):
    path = tmp_path / "credentials.json"
    assert pairing.load_router_credentials(path, "original token", " original password ") == ("original token", " original password ")
    assert pairing.load_router_credentials(path) == ("original token", " original password ")


@pytest.mark.parametrize("token", ["private-é-marker", " private-marker", "private-marker ", "private-marker\n", "private-marker\x7f", "private-marker\t"])
def test_header_unsupported_tokens_are_rejected_without_echo_or_regeneration(tmp_path, token):
    code = raw_code(json.dumps(payload(studioToken=token), ensure_ascii=True))
    with pytest.raises(pairing.PairingError) as error:
        pairing.decode_pairing(code)
    assert "private" not in str(error.value)
    path = tmp_path / "new-credentials.json"
    with pytest.raises(pairing.PairingError) as error:
        pairing.load_router_credentials(path, token, "existing-password")
    assert "private" not in str(error.value)
    assert not path.exists()
    original = json.dumps({"version": 1, "phone_studio_token": token, "tunnel_password": "existing-password"}).encode()
    path.write_bytes(original)
    with pytest.raises(pairing.PairingError):
        pairing.load_router_credentials(path)
    assert path.read_bytes() == original


def test_unknown_credential_file_and_foreign_lock_are_preserved(tmp_path):
    path = tmp_path / "credentials.json"
    path.write_text('{"unknown":"private-password"}', encoding="utf-8")
    original = path.read_bytes()
    with pytest.raises(pairing.PairingError) as error:
        pairing.load_router_credentials(path, "override-token", "override-password")
    assert "private-password" not in str(error.value)
    assert path.read_bytes() == original
    lock = path.with_name(path.name + ".lock")
    lock.write_text("foreign-owner", encoding="ascii")
    with pytest.raises(pairing.PairingError):
        pairing.load_router_credentials(path, timeout=0)
    assert lock.read_text() == "foreign-owner" and path.read_bytes() == original


def test_concurrent_first_start_uses_one_owned_credential_pair(tmp_path):
    root = Path(__file__).resolve().parents[2]
    path = tmp_path / "credentials.json"
    script = "import sys;sys.path.insert(0,sys.argv[1]);from tools.connection_pairing import load_router_credentials;load_router_credentials(sys.argv[2])"
    processes = [subprocess.Popen([sys.executable, "-I", "-c", script, str(root), str(path)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(3)]
    for process in processes:
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, stderr.decode()
        assert stdout == b""
    stored = json.loads(path.read_text())
    assert pairing.load_router_credentials(path) == (stored["phone_studio_token"], stored["tunnel_password"])
    assert not path.with_name(path.name + ".lock").exists()


@pytest.mark.parametrize("use_codes", [True, False])
def test_actual_router_configuration_cell_accepts_codes_or_existing_json(tmp_path, capsys, use_codes):
    root = Path(__file__).resolve().parents[2]
    notebook = json.loads((root / "PHONE_STUDIO_ROUTER_COLAB.ipynb").read_text(encoding="utf-8"))
    source = "".join(next(cell["source"] for cell in notebook["cells"] if cell["id"] == "router-config"))
    tree = ast.parse(source)
    # Execute only the saved configuration cell, with temporary storage and fake
    # Colab Secrets/mount. No dependencies, tunnels, GPU or model cells execute.
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in ("WORKSPACE", "ROUTER_DATA", "PERSISTENT_DATA"):
                node.value = ast.Call(func=ast.Name(id="Path", ctx=ast.Load()),
                                      args=[ast.Constant(str(tmp_path / name))], keywords=[])
    entry = {key: value for key, value in payload("worker", workerId="existing-worker").items() if key not in ("version", "kind")}
    settings = {"NGROK_AUTHTOKEN": "private-ngrok-token", "PHONE_STUDIO_TOKEN": "private-router-token",
                "TUNNEL_PASSWORD": "private-router-password", "PHONE_STUDIO_WORKERS_JSON": json.dumps([entry])}
    if use_codes:
        settings["PHONE_STUDIO_WORKER_CODES"] = pairing.encode_pairing(payload("worker", workerId="existing-worker"))
        settings["PHONE_STUDIO_WORKERS_JSON"] = "invalid-legacy-but-code-takes-precedence"
    colab = types.ModuleType("google.colab")
    colab.userdata = types.SimpleNamespace(get=lambda name: settings.get(name, ""))
    colab.drive = types.SimpleNamespace(mount=lambda _: None)
    namespace = {}
    with patch.dict(sys.modules, {"google.colab": colab}), patch.dict(os.environ, {}, clear=True):
        exec(compile(ast.fix_missing_locations(tree), "<saved-router-config>", "exec"), namespace)
        assert json.loads(os.environ["PHONE_STUDIO_WORKERS_JSON"]) == [entry]
        assert os.environ["PHONE_STUDIO_TOKEN"] == "private-router-token"
        assert os.environ["PHONE_STUDIO_ROUTER_PASSWORD"] == "private-router-password"
    assert namespace["worker_entries"] == [entry]
    assert "private-router" not in capsys.readouterr().out
