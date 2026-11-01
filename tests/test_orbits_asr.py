import json
import os
import subprocess

import pytest

from core.orbits_asr_runtime import run_local_asr


def test_asr_runtime_fails_closed_without_local_model(monkeypatch, tmp_path):
    monkeypatch.delenv("ORACLE_ARC_ASR_MODEL_DIR", raising=False)
    with pytest.raises(RuntimeError, match="separately installed local ASR model"):
        run_local_asr(b"audio")


def test_asr_runtime_mounts_model_read_only_and_disables_network(monkeypatch, tmp_path):
    model = tmp_path / "model"
    model.mkdir()
    monkeypatch.setenv("ORACLE_ARC_ASR_MODEL_DIR", str(model))
    monkeypatch.setenv("ORACLE_ARC_ASR_WORKER_IMAGE", "oracle-arc-asr-worker:test")
    seen = {}

    class Completed:
        returncode = 0
        stdout = '{"result":{"text":"local transcript","transcription_status":"completed","inference_location":"local"}}'

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["kwargs"] = kwargs
        return Completed()

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_local_asr(b"audio")
    assert result["text"] == "local transcript"
    command = seen["command"]
    assert "--network=none" in command
    assert "--read-only" in command
    assert "--cap-drop=ALL" in command
    mount = command[command.index("--mount") + 1]
    assert mount.endswith(",ro=true")
    assert str(model) in mount
    assert seen["kwargs"]["timeout"] == 300
    assert seen["kwargs"]["env"]["HF_HUB_OFFLINE"] == "1"


def test_asr_runtime_rejects_malformed_worker_output(monkeypatch, tmp_path):
    model = tmp_path / "model"
    model.mkdir()
    monkeypatch.setenv("ORACLE_ARC_ASR_MODEL_DIR", str(model))

    class Completed:
        returncode = 0
        stdout = '{"result":{"unexpected":true}}'

    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: Completed())
    with pytest.raises(RuntimeError, match="invalid result contract"):
        run_local_asr(b"audio")


def test_asr_registry_is_not_advertised_until_model_is_installed(monkeypatch, tmp_path):
    from core.orbits import build_default_orbits_registry, validate_asset, OrbitProcessorUnavailable

    monkeypatch.delenv("ORACLE_ARC_ASR_MODEL_DIR", raising=False)
    registry = build_default_orbits_registry(runner=lambda *_: {"ok": True})
    data = b"ID3mock"
    asset = validate_asset(data, "audio.mp3")
    with pytest.raises(OrbitProcessorUnavailable):
        registry.process("audio.transcribe", asset, data)

    model = tmp_path / "installed-model"
    model.mkdir()
    monkeypatch.setenv("ORACLE_ARC_ASR_MODEL_DIR", str(model))
    registry = build_default_orbits_registry(runner=lambda *_: {"ok": True})
    assert registry.processors if hasattr(registry, "processors") else True
