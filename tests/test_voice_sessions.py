from types import SimpleNamespace
import stat

import pytest

from core.voice_sessions import VoiceSessionError, VoiceSessionStore


def identity(principal="person-a"):
    return SimpleNamespace(tenant_id="tenant-a", application_id="app-a",
                           principal_id=principal, capabilities=frozenset())


def test_voice_session_lifecycle_and_event_replay(tmp_path):
    store = VoiceSessionStore(tmp_path / "voice.sqlite3")
    who = identity()
    created = store.create(who)
    session_id = created["session_id"]
    assert created["state"] == "created"
    assert created["raw_audio_retained"] is False

    assert store.transition(who, session_id, "capturing")["state"] == "capturing"
    assert store.transition(who, session_id, "uploaded")["state"] == "uploaded"
    assert store.transition(who, session_id, "transcribing")["state"] == "transcribing"
    assert store.transition(who, session_id, "awaiting_model")["state"] == "awaiting_model"
    assert store.transition(who, session_id, "synthesizing")["state"] == "synthesizing"
    assert store.transition(who, session_id, "ready")["state"] == "ready"

    first = store.events(who, session_id, after=0, limit=3)
    assert len(first) == 3
    second = store.events(who, session_id, after=first[-1]["event_id"])
    assert second[0]["event_id"] > first[-1]["event_id"]
    assert store.get(who, session_id)["state"] == "ready"


def test_voice_session_cancel_is_idempotent_and_terminal(tmp_path):
    store = VoiceSessionStore(tmp_path / "voice.sqlite3")
    who = identity()
    session_id = store.create(who)["session_id"]
    assert store.cancel(who, session_id)["state"] == "cancelled"
    repeated = store.cancel(who, session_id)
    assert repeated["state"] == "cancelled"
    assert repeated["idempotent"] is True
    with pytest.raises(VoiceSessionError):
        store.transition(who, session_id, "capturing")


def test_voice_session_isolation_between_principals(tmp_path):
    store = VoiceSessionStore(tmp_path / "voice.sqlite3")
    session_id = store.create(identity("person-a"))["session_id"]
    assert store.get(identity("person-b"), session_id) is None
    with pytest.raises(KeyError):
        store.events(identity("person-b"), session_id)


def test_voice_session_rejects_invalid_transition_and_cursor(tmp_path):
    store = VoiceSessionStore(tmp_path / "voice.sqlite3")
    who = identity()
    session_id = store.create(who)["session_id"]
    with pytest.raises(VoiceSessionError):
        store.transition(who, session_id, "playing")
    with pytest.raises(ValueError):
        store.events(who, session_id, after=-1)


def test_voice_session_database_is_private_to_the_service_user(tmp_path):
    database = tmp_path / "private" / "voice.sqlite3"
    store = VoiceSessionStore(database)
    assert stat.S_IMODE(database.stat().st_mode) == 0o600
    assert store.create(identity())["raw_audio_retained"] is False


def test_voice_session_events_reject_transcripts_and_arbitrary_user_content(tmp_path):
    store = VoiceSessionStore(tmp_path / "voice.sqlite3")
    who = identity()
    session_id = store.create(who)["session_id"]
    with pytest.raises(ValueError, match="cannot persist transcript"):
        store.transition(
            who, session_id, "capturing", event_type="session.capture",
            details={"transcript": "private spoken content"},
        )
    assert store.get(who, session_id)["state"] == "created"
    assert len(store.events(who, session_id)) == 1


def test_voice_session_event_metadata_is_bounded_and_scalar(tmp_path):
    store = VoiceSessionStore(tmp_path / "voice.sqlite3")
    who = identity()
    session_id = store.create(who)["session_id"]
    with pytest.raises(ValueError, match="metadata identifier is invalid"):
        store.transition(
            who, session_id, "capturing", details={"format": "x" * 129},
        )
    with pytest.raises(ValueError, match="metadata number is out of range"):
        store.transition(
            who, session_id, "capturing", details={"duration_seconds": float("inf")},
        )
    assert store.get(who, session_id)["state"] == "created"
