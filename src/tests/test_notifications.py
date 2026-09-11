import time

from notifications import ProgressNotifier
from tools.base import BaseTool


class SlowLabelLLM:
    def chat(self, *args, **kwargs):
        time.sleep(0.05)
        return {"content": "Checking forecast"}


class FailingLLM:
    def chat(self, *args, **kwargs):
        raise RuntimeError("missing model")


class LevelOneTool(BaseTool):
    progress_level = 1
    name = "level_one"
    description = "test"
    parameters = {}

    def execute(self, **kwargs):
        return {}


def test_progress_log_pairs_generated_pending_and_resolved():
    progress = ProgressNotifier(SlowLabelLLM())
    q = progress.subscribe()

    first = progress.generated(level=2, name="weather_forecast", description="Weather", arguments={"city": "Tokyo"})
    second = progress.static_pending(level=2, label="Checking cache")
    progress.resolve(second)
    progress.resolve(first)

    events = [q.get(timeout=1), q.get(timeout=1), q.get(timeout=1), q.get(timeout=1)]

    assert [(e.entry_id, e.status, e.label) for e in events] == [
        (second, "pending", "Checking cache"),
        (second, "resolved", "Checking cache"),
        (first, "pending", "Checking forecast"),
        (first, "resolved", "Checking forecast"),
    ]


def test_static_pending_resolves_later():
    progress = ProgressNotifier()
    q = progress.subscribe()

    entry_id = progress.static_pending(level=2, label="Checking cache")
    progress.resolve(entry_id)

    events = [q.get(timeout=1), q.get(timeout=1)]
    assert [(e.entry_id, e.status, e.label) for e in events] == [
        (entry_id, "pending", "Checking cache"),
        (entry_id, "resolved", "Checking cache"),
    ]


def test_tool_static_defaults_to_level_two_with_parent():
    progress = ProgressNotifier()
    q = progress.subscribe()
    tool = LevelOneTool()
    tool.progress_notifier = progress

    with progress.parent("n1"):
        entry_id = tool.notify_static_pending("Checking cache")
    tool.notify_static_resolved(entry_id)

    events = [q.get(timeout=1), q.get(timeout=1)]
    assert [(e.level, e.parent_id) for e in events] == [(2, "n1"), (2, "n1")]


def test_level_two_events_include_current_parent():
    progress = ProgressNotifier(SlowLabelLLM())
    q = progress.subscribe()

    with progress.parent("n1"):
        child = progress.generated(level=2, name="weather_forecast", description="Weather", arguments={"city": "Tokyo"})
    progress.resolve(child)

    events = [q.get(timeout=1), q.get(timeout=1)]
    assert events[0].parent_id == "n1"
    assert events[1].parent_id == "n1"


def test_failed_generation_marks_placeholder():
    progress = ProgressNotifier(FailingLLM())
    q = progress.subscribe()

    entry_id = progress.generated(level=2, name="weather_forecast", description="Weather", arguments={"city": "Tokyo"})
    progress.resolve(entry_id)

    events = [q.get(timeout=1), q.get(timeout=1)]
    assert events[0].status == "pending"
    assert events[0].label.endswith(" (placeholder)")
    assert events[1].status == "resolved"
    assert events[1].label == events[0].label
