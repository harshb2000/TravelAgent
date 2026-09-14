from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Protocol

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from notifications import ProgressEvent, ProgressNotifier


@dataclass
class Artifact:
    id: str
    name: str
    content: str


@dataclass
class AgentSession:
    session_id: str
    notifier: ProgressNotifier = field(default_factory=ProgressNotifier)
    artifacts: dict[str, Artifact] = field(default_factory=dict)
    workdir: Path = field(default_factory=lambda: Path(tempfile.mkdtemp(prefix="travelagent-")))
    orchestrator: object | None = None
    lock: Lock = field(default_factory=Lock)

    def refresh_artifacts(self) -> None:
        for path in sorted(self.workdir.glob("*.md")):
            artifact_id = path.name
            self.artifacts[artifact_id] = Artifact(
                id=artifact_id,
                name=path.name,
                content=path.read_text(encoding="utf-8"),
            )


class SessionStore(Protocol):
    def get(self, session_id: str) -> AgentSession: ...


class InMemorySessionStore:
    def __init__(self):
        self._sessions: dict[str, AgentSession] = {}
        self._lock = Lock()

    def get(self, session_id: str) -> AgentSession:
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = AgentSession(session_id=session_id)
            return self._sessions[session_id]


def sse(event: ProgressEvent) -> str:
    data = {
        "entry_id": event.entry_id,
        "level": event.level,
        "status": event.status,
        "label": event.label,
        "parent_id": event.parent_id,
    }
    return f"id: {event.entry_id}\nevent: progress\ndata: {json.dumps(data)}\n\n"


from tools.file_write import FileWriteTool


class FakeOrchestrator:
    def __init__(self, session: AgentSession):
        self.session = session

    def turn(self, message: str) -> str:
        parent = self.session.notifier.static_pending(level=1, label="Planning Tokyo trip")
        child = self.session.notifier.static_pending(level=2, label="Checking flights", parent_id=parent)
        self.session.notifier.resolve(child)
        self.session.notifier.resolve(parent)
        FileWriteTool(self.session.workdir).execute(subject="tokyo_plan", content=f"# Tokyo Plan\n\nYou asked: {message}")
        return f"Planned it.\n\n- Message: **{message}**"


def build_orchestrator(session: AgentSession):
    if os.getenv("TRAVELAGENT_FAKE") == "1":
        return FakeOrchestrator(session)

    from agent.factory import build_orchestrator as build_agent, configure_progress_notifier

    configure_progress_notifier(session.notifier)
    return build_agent(progress=session.notifier, file_write=FileWriteTool(session.workdir))
