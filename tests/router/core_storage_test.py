"""CPU-only validation, persistence and image-storage boundary tests."""
import copy
from pathlib import Path

import pytest
from PIL import Image

from router.assets import AssetStore
from router.config import Config, RouterError, WorkerConfig, validate_request
from router.journal import Journal


def request():
    return {"schemaVersion": 2, "clientId": "client-1", "requestId": "request-1", "operation": "generate",
            "originalPrompt": "two cats in a garden", "negativePrompt": "text",
            "parameters": {"model": "model.safetensors", "baseSeed": 1001}}


def settings(tmp_path):
    return Config(tmp_path / "local", tmp_path / "drive", "secret", disk_reserve_bytes=0)


def test_valid_request_has_two_presets_and_default_on_options():
    result = validate_request(request())
    assert result["options"] == {"enhancePrompt": True, "reviewCandidates": True, "auxiliaryInpaint": True}
    assert result["parameters"]["preset"] == "balanced"
    assert result["parameters"]["speedExtras"] is True


@pytest.mark.parametrize("mutate", [
    lambda body: body.update(workerUrl="https://example.org"),
    lambda body: body.update(prompt={"1": {"class_type": "RunCode"}}),
    lambda body: body.update(clientId="../escape"),
    lambda body: body.update(schemaVersion=True),
    lambda body: body["parameters"].update(model="C:/private.safetensors"),
    lambda body: body["parameters"].update(model="../private.safetensors"),
    lambda body: body["parameters"].update(baseSeed=True),
    lambda body: body["parameters"].update(loraStrength=float("nan")),
    lambda body: body["parameters"].update(preset="lightning"),
    lambda body: body["parameters"].update(width=2048, height=2048),
    lambda body: body.update(options={"reviewCandidates": "true"}),
    lambda body: body.update(options={"auxiliaryInpaint": "true"}),
    lambda body: body.update(originalPrompt="x" * 8001),
])
def test_invalid_inputs_are_rejected(mutate):
    body = request()
    mutate(body)
    with pytest.raises(RouterError):
        validate_request(body)


@pytest.mark.parametrize("url", ["http://remote.test", "https://name:password@example.org", "https://example.org/?token=secret", "file:///private"])
def test_worker_configuration_rejects_unsafe_endpoints(url):
    with pytest.raises(RouterError):
        WorkerConfig.from_dict({"workerId": "w1", "serverUrl": url, "studioToken": "secret"})


def test_acceptance_replay_conflict_and_restore_from_drive(tmp_path):
    config = settings(tmp_path)
    journal = Journal(config.root, config.drive)
    body = validate_request(request())
    first, created = journal.create_job(body, [], 900)
    assert created
    replay, created = journal.create_job(copy.deepcopy(body), [], 900)
    assert not created and replay["jobId"] == first["jobId"]
    conflicting = copy.deepcopy(body)
    conflicting["originalPrompt"] = "a different request"
    with pytest.raises(RouterError) as caught:
        journal.create_job(conflicting, [], 900)
    assert caught.value.status == 409
    studio_id = journal.studio_id
    journal.close()
    restored = Journal(tmp_path / "new-runtime", config.drive)
    try:
        assert restored.studio_id == studio_id
        assert restored.recover("client-1", "request-1")["jobId"] == first["jobId"]
    finally:
        restored.close()


def test_local_wal_and_concurrent_local_router_guard(tmp_path):
    config = settings(tmp_path)
    with pytest.raises(RouterError):
        Journal(config.drive / "live", config.drive)
    journal = Journal(config.root, config.drive)
    try:
        with pytest.raises(RouterError):
            Journal(config.root, config.drive)
        assert journal.db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        journal.close()


def test_retry_key_is_reserved_atomically_and_replay_is_read(tmp_path):
    config = settings(tmp_path)
    journal = Journal(config.root, config.drive)
    try:
        first, _ = journal.create_job(validate_request(request()), [], 900)
        revised, created = journal.retry(first["jobId"], "retry-1", lambda job: job.update(state="dispatching"))
        assert created and revised["revision"] == 2
        again, created = journal.retry(first["jobId"], "retry-1", lambda job: pytest.fail("Replay executed the transition"))
        assert not created and again["revision"] == 2
    finally:
        journal.close()


def test_asset_orientation_alpha_dedup_and_durable_read(tmp_path):
    config = settings(tmp_path)
    journal = Journal(config.root, config.drive)
    try:
        store = AssetStore(config, journal)
        source = tmp_path / "source.png"
        image = Image.new("RGBA", (16, 24), (10, 20, 30, 100))
        exif = Image.Exif(); exif[274] = 6
        image.save(source, exif=exif)
        asset = store.ingest(source)
        assert (asset["width"], asset["height"]) == (24, 16)
        assert store.ingest(source)["assetId"] == asset["assetId"]
        with Image.open(store.path(asset["assetId"])) as opened:
            assert opened.mode == "RGBA" and opened.getpixel((0, 0)) == (10, 20, 30, 100)
            assert not opened.getexif()
        store.path(asset["assetId"]).unlink()
        assert store.path(asset["assetId"]).parent == store.persistent
        with pytest.raises(RouterError):
            store.path("../outside")
    finally:
        journal.close()


def test_bad_upload_mask_kind_quota_and_animation(tmp_path):
    config = settings(tmp_path)
    journal = Journal(config.root, config.drive)
    try:
        store = AssetStore(config, journal)
        bad = tmp_path / "script.svg"; bad.write_text("<svg/>")
        with pytest.raises(RouterError):
            store.ingest(bad)
        image = tmp_path / "image.png"; Image.new("RGB", (16, 16), "red").save(image)
        with pytest.raises(RouterError):
            store.ingest(image, "script")
        config.asset_quota_bytes = 1
        with pytest.raises(RouterError) as caught:
            store.ingest(image)
        assert caught.value.status == 507
        config.asset_quota_bytes = 1024**2
        animated = tmp_path / "animation.png"
        Image.new("RGB", (16, 16), "red").save(animated, save_all=True, append_images=[Image.new("RGB", (16, 16), "blue")])
        with pytest.raises(RouterError):
            store.ingest(animated)
        mask = store.ingest(image, "mask")
        assert mask["kind"] == "mask"
        with Image.open(store.path(mask["assetId"])) as opened:
            assert opened.mode == "L"
    finally:
        journal.close()
