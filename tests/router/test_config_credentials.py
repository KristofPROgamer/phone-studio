"""Direct legacy configuration fixtures; no notebook setup or network activity."""
import copy
import json
import os
from unittest.mock import patch

from aiohttp import BasicAuth, encode_basic_auth
import pytest

from router.config import Config, RouterError, WorkerConfig


def entry(**updates):
    return {"workerId": "existing-worker", "name": "Existing worker", "serverUrl": "http://127.0.0.1:8188",
            "tunnelUser": "", "tunnelPassword": "", "studioToken": "existing-token"} | updates


def environment(worker=None, **updates):
    return {"PHONE_STUDIO_WORKERS_JSON": json.dumps([worker or entry()]), "PHONE_STUDIO_TOKEN": "router-token"} | updates


@pytest.mark.parametrize("user,password", [("", ""), ("studio", ""), ("", "unused-password")])
def test_legacy_token_only_basic_fields_remain_supported(user, password):
    source = entry(tunnelUser=user, tunnelPassword=password)
    original = copy.deepcopy(source)
    worker = WorkerConfig.from_dict(source)
    assert (worker.tunnel_user, worker.tunnel_password, worker.studio_token) == (user, password, "existing-token")
    assert source == original
    with patch.dict(os.environ, environment(source), clear=True):
        config = Config.from_env()
        assert config.workers == (worker,)
        assert config.basic_user == "" and config.basic_password == ""


def test_legacy_latin1_auth_and_password_outer_spaces_preserve_exact_values():
    user, password = "stúdio", " é-password: trailing "
    source = entry(tunnelUser=user, tunnelPassword=password)
    worker = WorkerConfig.from_dict(source)
    decoded = BasicAuth.decode(encode_basic_auth(worker.tunnel_user, worker.tunnel_password, encoding="latin1"))
    assert decoded.login == user and decoded.password == password
    values = environment(source, PHONE_STUDIO_ROUTER_USER=user, PHONE_STUDIO_ROUTER_PASSWORD=password)
    original = copy.deepcopy(values)
    with patch.dict(os.environ, values, clear=True):
        config = Config.from_env()
        assert config.basic_user == user and config.basic_password == password
        assert dict(os.environ) == original


@pytest.mark.parametrize("field,value", [
    ("tunnelUser", "astral-😀-marker"), ("tunnelUser", "user:marker"), ("tunnelUser", " user-marker"),
    ("tunnelUser", "user\nmarker"), ("tunnelPassword", "astral-😀-marker"),
    ("tunnelPassword", "control-\x85-marker"), ("tunnelPassword", "control-\x7f-marker"),
    ("tunnelPassword", "control-\n-marker"), ("tunnelPassword", "   "),
    ("studioToken", "unicode-é-marker"), ("studioToken", " token-marker"), ("studioToken", "token-marker "),
    ("studioToken", "line\nmarker"), ("studioToken", "control-\x7f-marker"),
])
def test_legacy_json_rejects_unsupported_credentials_without_echo_or_mutation(field, value):
    source = entry(**{field: value})
    original = copy.deepcopy(source)
    with pytest.raises(RouterError) as error:
        WorkerConfig.from_dict(source)
    assert "marker" not in str(error.value)
    assert value not in str(error.value)
    assert source == original
    values = environment(source)
    with patch.dict(os.environ, values, clear=True):
        with pytest.raises(RouterError):
            Config.from_env()
        assert os.environ["PHONE_STUDIO_WORKERS_JSON"] == values["PHONE_STUDIO_WORKERS_JSON"]


@pytest.mark.parametrize("field,value", [
    ("PHONE_STUDIO_TOKEN", "unicode-é-marker"), ("PHONE_STUDIO_TOKEN", " token-marker"),
    ("PHONE_STUDIO_TOKEN", "token-marker "), ("PHONE_STUDIO_TOKEN", "line\nmarker"),
    ("PHONE_STUDIO_ROUTER_USER", "astral-😀-marker"), ("PHONE_STUDIO_ROUTER_USER", "user:marker"),
    ("PHONE_STUDIO_ROUTER_PASSWORD", "astral-😀-marker"), ("PHONE_STUDIO_ROUTER_PASSWORD", "control-\x85-marker"),
])
def test_router_environment_rejects_unsupported_credentials_without_echo_or_mutation(field, value):
    values = environment(**{field: value})
    with patch.dict(os.environ, values, clear=True):
        with pytest.raises(RouterError) as error:
            Config.from_env()
        assert "marker" not in str(error.value) and value not in str(error.value)
        assert os.environ[field] == value


def test_interior_ascii_token_spaces_remain_exact_for_header_auth():
    source = entry(studioToken="opaque interior token")
    assert WorkerConfig.from_dict(source).studio_token == "opaque interior token"
    with patch.dict(os.environ, environment(source, PHONE_STUDIO_TOKEN="router interior token"), clear=True):
        assert Config.from_env().token == "router interior token"
