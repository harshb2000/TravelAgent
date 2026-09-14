from unittest.mock import patch
from uuid import uuid4

from api.sessions import InMemorySessionStore, ProgressEvent, sse


def test_sessions_are_isolated():
    store = InMemorySessionStore()
    first, second = store.get(str(uuid4())), store.get(str(uuid4()))
    first.artifacts["plan.md"] = object()

    assert first is store.get(first.session_id)
    assert second.session_id != first.session_id
    assert second.artifacts == {}
    assert first.notifier is not second.notifier


def test_existing_session_is_not_reconstructed():
    store = InMemorySessionStore()
    with patch("api.sessions.AgentSession") as constructor:
        constructor.return_value = object()
        assert store.get("same") is store.get("same")
    constructor.assert_called_once_with(session_id="same")


def test_progress_event_sse_serialization():
    payload = sse(ProgressEvent("n2", 2, "resolved", "Checking flights", "n1"))

    assert payload.startswith("id: n2\nevent: progress\n")
    assert '"entry_id": "n2"' in payload
    assert '"level": 2' in payload
    assert '"status": "resolved"' in payload
    assert '"parent_id": "n1"' in payload
    assert payload.endswith("\n\n")
