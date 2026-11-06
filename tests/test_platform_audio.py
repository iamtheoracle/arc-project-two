import base64
from types import SimpleNamespace

from fastapi.testclient import TestClient

from api import app
from core.platform_routes import require_application


def test_audio_synthesis_requires_explicit_capability(monkeypatch):
    app.dependency_overrides[require_application] = lambda: SimpleNamespace(capabilities=set())
    try:
        response = TestClient(app).post(
            "/v1/platform/audio/synthesize", json={"text": "Hello"}
        )
        assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(require_application, None)


def test_audio_synthesis_uses_local_worker_and_returns_ephemeral_audio(monkeypatch):
    identity = SimpleNamespace(capabilities={"audio.synthesize"})
    app.dependency_overrides[require_application] = lambda: identity
    import core.orbits_tts_runtime as runtime
    monkeypatch.setattr(runtime, "run_local_tts", lambda text, voice_id: {
        "format": "audio/wav", "audio_base64": base64.b64encode(b"RIFFmock").decode(),
        "synthesis_status": "completed", "inference_location": "local",
        "voice_id": voice_id, "sha256": "a" * 64,
    })
    try:
        response = TestClient(app).post(
            "/v1/platform/audio/synthesize",
            json={"text": "Hello from Oracle Arc", "voice_id": "local-default"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["delivery"] == "ephemeral"
        assert payload["retained"] is False
        assert payload["audio"]["inference_location"] == "local"
    finally:
        app.dependency_overrides.pop(require_application, None)


def test_audio_voice_catalogue_is_capability_scoped():
    app.dependency_overrides[require_application] = lambda: SimpleNamespace(capabilities=set())
    try:
        response = TestClient(app).get("/v1/platform/audio/voices")
        assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(require_application, None)


def test_orbits_transcription_requires_dedicated_capability():
    identity = SimpleNamespace(capabilities={"orbits.process"})
    app.dependency_overrides[require_application] = lambda: identity
    try:
        response = TestClient(app).post(
            "/v1/platform/orbits/process",
            json={
                "processor_id": "audio.transcribe",
                "filename": "meeting.wav",
                "mime_type": "audio/wav",
                "data_base64": base64.b64encode(b"audio").decode(),
            },
        )
        assert response.status_code == 403
        assert "audio.transcribe" in response.json()["detail"]
    finally:
        app.dependency_overrides.pop(require_application, None)


def test_orbits_audio_inspection_requires_dedicated_capability():
    identity = SimpleNamespace(capabilities={"orbits.process"})
    app.dependency_overrides[require_application] = lambda: identity
    try:
        response = TestClient(app).post(
            "/v1/platform/orbits/process",
            json={
                "processor_id": "audio.inspect",
                "filename": "meeting.wav",
                "mime_type": "audio/wav",
                "data_base64": base64.b64encode(b"audio").decode(),
            },
        )
        assert response.status_code == 403
        assert "audio.inspect" in response.json()["detail"]
    finally:
        app.dependency_overrides.pop(require_application, None)

def test_voice_catalogue_does_not_claim_tts_ready_from_env_path(monkeypatch, tmp_path):
    identity = SimpleNamespace(capabilities={"audio.synthesize"})
    app.dependency_overrides[require_application] = lambda: identity
    monkeypatch.setenv("ORACLE_ARC_TTS_MODEL_DIR", str(tmp_path / "missing-model"))
    try:
        response = TestClient(app).get("/v1/platform/audio/voices")
        assert response.status_code == 200
        voice = response.json()["voices"][0]
        assert voice["configuration_status"] == "not_configured"
        assert voice["runtime_health"] == "not_probed"
        assert voice["real_inference_verified"] is False
    finally:
        app.dependency_overrides.pop(require_application, None)
