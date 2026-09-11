import itertools
import queue
import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Lock, Thread
from typing import Iterator

from clients.llm_client import LLMClient


@dataclass(frozen=True)
class ProgressEvent:
    entry_id: str
    level: int
    status: str
    label: str
    parent_id: str | None = None


@dataclass
class _ProgressState:
    level: int
    parent_id: str | None = None
    label: str | None = None
    pending_emitted: bool = False
    done: bool = False


class ProgressNotifier:
    def __init__(self, llm: LLMClient | None = None, timeout_s: float = 15.0):
        self._llm = llm
        self._timeout_s = timeout_s
        self._ids = itertools.count(1)
        self._states: dict[str, _ProgressState] = {}
        self._subscribers: list[queue.Queue[ProgressEvent]] = []
        self._lock = Lock()
        self._local = threading.local()

    def subscribe(self) -> queue.Queue[ProgressEvent]:
        q: queue.Queue[ProgressEvent] = queue.Queue()
        with self._lock:
            self._subscribers.append(q)
        return q

    def events(self, q: queue.Queue[ProgressEvent]) -> Iterator[ProgressEvent]:
        while True:
            yield q.get()

    def current_parent_id(self) -> str | None:
        return getattr(self._local, "parent_id", None)

    @contextmanager
    def parent(self, parent_id: str | None):
        old = self.current_parent_id()
        self._local.parent_id = parent_id
        try:
            yield
        finally:
            self._local.parent_id = old

    def generated(self, *, level: int, name: str, description: str, arguments: dict, placeholder: str | None = None, parent_id: str | None = None) -> str:
        entry_id = f"n{next(self._ids)}"
        placeholder_label = f"{placeholder or name.replace('_', ' ')} (placeholder)"
        parent_id = parent_id or (self.current_parent_id() if level > 1 else None)
        with self._lock:
            self._states[entry_id] = _ProgressState(level=level, parent_id=parent_id)
        Thread(
            target=self._generate_and_emit_pending,
            args=(entry_id, level, placeholder_label, name, description, arguments),
            daemon=True,
        ).start()
        return entry_id

    def resolve(self, entry_id: str) -> None:
        event: ProgressEvent | None = None
        with self._lock:
            state = self._states[entry_id]
            state.done = True
            if state.pending_emitted and state.label:
                event = ProgressEvent(entry_id, state.level, "resolved", state.label, state.parent_id)
        if event:
            self._emit(event)

    def static_pending(self, *, level: int, label: str, parent_id: str | None = None) -> str:
        entry_id = f"n{next(self._ids)}"
        parent_id = parent_id or (self.current_parent_id() if level > 1 else None)
        with self._lock:
            self._states[entry_id] = _ProgressState(level=level, parent_id=parent_id, label=label, pending_emitted=True)
        self._emit(ProgressEvent(entry_id, level, "pending", label, parent_id))
        return entry_id

    def _generate_and_emit_pending(self, entry_id: str, level: int, placeholder: str, name: str, description: str, arguments: dict) -> None:
        try:
            label = self._generate(name, description, arguments) or placeholder
        except Exception:
            label = placeholder

        resolved_event: ProgressEvent | None = None
        with self._lock:
            state = self._states[entry_id]
            state.label = label
            state.pending_emitted = True
            pending_event = ProgressEvent(entry_id, level, "pending", label, state.parent_id)
            if state.done:
                resolved_event = ProgressEvent(entry_id, level, "resolved", label, state.parent_id)
        self._emit(pending_event)
        if resolved_event:
            self._emit(resolved_event)

    def _emit(self, event: ProgressEvent) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            q.put(event)

    def _generate(self, name: str, description: str, arguments: dict) -> str:
        msg = self._llm.chat(
            [
                {"role": "system", "content": "Write only a traveler-facing progress label for work currently running. Use 3-8 words. Mention the destination or topic when available. Do not mention internal implementation words like specialist, tool, function, API, model, wrapper, or agent. Examples: Exploring activities in Varkala, Looking up things to do in Varkala, Checking weather in Tokyo. No punctuation."},
                {"role": "user", "content": f"name: {name}\ndescription: {description}\narguments: {arguments}"},
            ],
            timeout=self._timeout_s,
            retries=0,
            extra_body={"reasoning_effort": "none"},
        )
        text = (msg.get("content") or "").strip()
        return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip().splitlines()[0].strip(' \"\'')[:80]
