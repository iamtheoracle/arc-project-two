import json
import subprocess

import pytest

from core.orbits_runtime import run_isolated_orbits_processor


def test_orbits_runner_uses_restricted_podman_container(monkeypatch):
    seen = {}

    class Completed:
        returncode = 0
        stdout = '{"result":{"text":"extracted"}}'

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["kwargs"] = kwargs
        return Completed()

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_isolated_orbits_processor("document.extract", b"safe text")
    assert result == {"text": "extracted"}
    command = seen["command"]
    for flag in (
        "--network=none", "--ipc=none", "--read-only", "--cap-drop=ALL",
        "--security-opt=no-new-privileges", "--pids-limit=32",
        "--memory=512m", "--memory-swap=512m", "--cpus=1",
        "--user=65534:65534",
    ):
        assert flag in command
    assert seen["kwargs"]["timeout"] == 60
    assert seen["kwargs"]["check"] is False
    payload = json.loads(seen["kwargs"]["input"])
    assert payload["processor_id"] == "document.extract"
    assert payload["data_base64"]


def test_orbits_runner_fails_closed_on_timeout_and_unknown_processor(monkeypatch):
    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("podman", 60)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(TimeoutError, match="60-second deadline"):
        run_isolated_orbits_processor("image.ocr", b"image")
    with pytest.raises(ValueError, match="not allowlisted"):
        run_isolated_orbits_processor("arbitrary.command", b"image")


def test_orbits_default_registry_uses_only_isolated_platform_processors():
    from core.orbits import build_default_orbits_registry

    registry = build_default_orbits_registry(runner=lambda processor, data: {"processor": processor})
    for processor_id, media_type, data, filename in (
        ("document.extract", "document", b"plain text", "note.txt"),
        ("image.ocr", "image", b"\x89PNG\r\n\x1a\nmock", "image.png"),
        ("audio.inspect", "audio", b"ID3mock", "voice.mp3"),
    ):
        asset = __import__("core.orbits", fromlist=["validate_asset"]).validate_asset(data, filename)
        result = registry.process(processor_id, asset, data)
        assert result["processor"] == processor_id
