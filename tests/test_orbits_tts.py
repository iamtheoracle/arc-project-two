import base64
import hashlib
import io
import json
import sys
import types
import wave

import pytest

from core.orbits_tts_runtime import run_local_tts
from core.orbits_tts_worker import execute


def _model_dir(tmp_path):
    model = tmp_path / "voice"
    model.mkdir()
    model_bytes = b"fake-onnx-model"
    config_bytes = b'{"audio":{"sample_rate":22050}}'
    (model / "voice.onnx").write_bytes(model_bytes)
    (model / "voice.onnx.json").write_bytes(config_bytes)
    (model / "oracle-arc-tts-manifest.json").write_text(json.dumps({
        "repo_id": "test/piper-voice", "revision": "a" * 40, "license": "test-license",
        "sha256": {
            "voice.onnx": hashlib.sha256(model_bytes).hexdigest(),
            "voice.onnx.json": hashlib.sha256(config_bytes).hexdigest(),
        },
    }))
    return model


def _valid_tts_result():
    audio_buffer = io.BytesIO()
    with wave.open(audio_buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        wav_file.writeframes(b"\x00\x00" * 2205)
    audio = audio_buffer.getvalue()
    return {
        "synthesis_status": "completed", "inference_location": "local",
        "format": "audio/wav", "audio_base64": base64.b64encode(audio).decode(),
        "sha256": hashlib.sha256(audio).hexdigest(), "sample_rate_hz": 22050,
        "channels": 1, "size_bytes": len(audio),
    }


def _fake_piper(monkeypatch):
    class FakeVoice:
        @staticmethod
        def load(model_path, config_path):
            assert model_path == "/models/active/voice.onnx"
            assert config_path == "/models/active/voice.onnx.json"
            return FakeVoice()

        def synthesize_wav(self, text, wav_file):
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22050)
            wav_file.writeframes(b"\x00\x00" * 2205)

    monkeypatch.setitem(sys.modules, "piper", types.SimpleNamespace(PiperVoice=FakeVoice))


def test_tts_worker_produces_bounded_local_wav(monkeypatch, tmp_path):
    model = _model_dir(tmp_path)
    monkeypatch.setattr("core.orbits_tts_worker._verify_model", lambda _: json.loads(
        (model / "oracle-arc-tts-manifest.json").read_text()))
    _fake_piper(monkeypatch)
    result = execute({
        "processor_id": "audio.synthesize", "text": "Hello there", "voice_id": "local-default",
    })
    audio = base64.b64decode(result["audio_base64"], validate=True)
    assert audio.startswith(b"RIFF")
    assert result["format"] == "audio/wav"
    assert result["sample_rate_hz"] == 22050
    assert result["duration_seconds"] == 0.1
    assert result["inference_location"] == "local"
    assert result["synthesis_status"] == "completed"
    assert result["sha256"] == hashlib.sha256(audio).hexdigest()


def test_tts_worker_rejects_unknown_voice_and_oversized_text():
    with pytest.raises(ValueError, match="not allowlisted"):
        execute({"processor_id": "audio.synthesize", "text": "Hi", "voice_id": "arbitrary"})
    with pytest.raises(ValueError, match="4,000"):
        execute({"processor_id": "audio.synthesize", "text": "x" * 4001, "voice_id": "local-default"})


def test_tts_worker_checks_model_manifest_and_hashes(tmp_path):
    model = _model_dir(tmp_path)
    manifest = json.loads((model / "oracle-arc-tts-manifest.json").read_text())
    manifest["sha256"]["voice.onnx"] = "0" * 64
    (model / "oracle-arc-tts-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        from core.orbits_tts_worker import _verify_model
        _verify_model(str(model))


def test_tts_runtime_fails_closed_without_model(monkeypatch):
    monkeypatch.delenv("ORACLE_ARC_TTS_MODEL_DIR", raising=False)
    with pytest.raises(RuntimeError, match="separately installed local TTS model"):
        run_local_tts("Hello")


def test_tts_runtime_uses_isolated_read_only_offline_container(monkeypatch, tmp_path):
    model = _model_dir(tmp_path)
    monkeypatch.setenv("ORACLE_ARC_TTS_MODEL_DIR", str(model))
    monkeypatch.setenv("ORACLE_ARC_TTS_WORKER_IMAGE", "oracle-arc-tts-worker:test")
    seen = {}

    class Completed:
        returncode = 0
        stdout = json.dumps({"result": _valid_tts_result()})

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["kwargs"] = kwargs
        return Completed()

    monkeypatch.setattr("core.orbits_tts_runtime.subprocess.run", fake_run)
    result = run_local_tts("Hello")
    assert result["inference_location"] == "local"
    command = seen["command"]
    assert "--network=none" in command and "--read-only" in command
    assert "--cap-drop=ALL" in command and "--pull=never" in command
    assert command[command.index("--mount") + 1].endswith(",ro=true")
    assert seen["kwargs"]["timeout"] == 120


def test_tts_runtime_rejects_unknown_voice_and_malformed_output(monkeypatch, tmp_path):
    model = _model_dir(tmp_path)
    monkeypatch.setenv("ORACLE_ARC_TTS_MODEL_DIR", str(model))
    with pytest.raises(ValueError, match="reviewed local voice"):
        run_local_tts("Hello", "unreviewed")
    class Completed:
        returncode = 0
        stdout = '{"result":{"synthesis_status":"completed"}}'
    monkeypatch.setattr("core.orbits_tts_runtime.subprocess.run", lambda *_a, **_k: Completed())
    with pytest.raises(RuntimeError, match="invalid result contract"):
        run_local_tts("Hello")
