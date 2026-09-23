#!/usr/bin/env python3
"""Temporary, opt-in end-to-end timing runner.

Usage:
    python src/scripts/e2e_timing.py --phase 1 --debug
    python src/scripts/e2e_timing.py --phase 2 --attempts 5 --debug

Outputs are written under src/eval/results/e2e_timing/, which is gitignored.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import statistics
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

ALL_SPECIALISTS = {
    "explorer",
    "weather",
    "destination_research",
    "transportation",
    "budget",
    "itinerary_planner",
    "artifact",
}


class TimingRecorder:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_id = 0
        self._open: dict[int, tuple[str, str, float, dict[str, Any]]] = {}
        self.events: list[dict[str, Any]] = []
        self.case_started: float | None = None
        self.case_ended: float | None = None
        self.active = False

    def begin(self, kind: str, name: str, **metadata: Any) -> int | None:
        with self._lock:
            if not self.active or self.case_started is None:
                return None
            self._next_id += 1
            event_id = self._next_id
            self._open[event_id] = (kind, name, time.perf_counter(), metadata)
            return event_id

    def end(self, event_id: int | None, status: str = "ok", **metadata: Any) -> None:
        if event_id is None:
            return
        ended = time.perf_counter()
        with self._lock:
            item = self._open.pop(event_id, None)
            if item is None or self.case_started is None:
                return
            kind, name, started, original_metadata = item
            event = {
                "id": event_id,
                "kind": kind,
                "name": name,
                "start_ms": round((started - self.case_started) * 1000, 2),
                "end_ms": round((ended - self.case_started) * 1000, 2),
                "duration_ms": round((ended - started) * 1000, 2),
                "status": status,
                **original_metadata,
                **metadata,
            }
            self.events.append(event)

    @contextmanager
    def span(self, kind: str, name: str, **metadata: Any) -> Iterator[None]:
        event_id = self.begin(kind, name, **metadata)
        try:
            yield
        except Exception as exc:
            self.end(event_id, "error", error=f"{type(exc).__name__}: {exc}")
            raise
        else:
            self.end(event_id)

    def start_case(self) -> None:
        self.case_started = time.perf_counter()
        self.active = True

    def end_case(self) -> None:
        self.case_ended = time.perf_counter()
        self.active = False

    @property
    def case_duration_ms(self) -> float | None:
        if self.case_started is None or self.case_ended is None:
            return None
        return round((self.case_ended - self.case_started) * 1000, 2)


class TimingHooks:
    """Monkey-patches existing classes only while this temporary runner is active."""

    def __init__(self, recorder: TimingRecorder, llm_cls: type, notifier_cls: type) -> None:
        self.recorder = recorder
        self.llm_cls = llm_cls
        self.notifier_cls = notifier_cls
        self._original_chat = None
        self._original_generated = None
        self._original_static_pending = None
        self._original_resolve = None
        self._notifier_spans: dict[tuple[int, str], int | None] = {}

    def __enter__(self) -> "TimingHooks":
        self._original_chat = self.llm_cls.chat
        self._original_generated = self.notifier_cls.generated
        self._original_static_pending = self.notifier_cls.static_pending
        self._original_resolve = self.notifier_cls.resolve

        original_chat = self._original_chat
        original_generated = self._original_generated
        original_static_pending = self._original_static_pending
        original_resolve = self._original_resolve
        recorder = self.recorder
        spans = self._notifier_spans

        def timed_chat(instance, messages, timeout, tools=None, extra_body=None, retries=None):
            system = messages[0].get("content", "") if messages else ""
            scope = prompt_scope(system)
            tool_names = [
                tool.get("function", {}).get("name")
                for tool in (tools or [])
                if tool.get("function", {}).get("name")
            ]
            event_id = recorder.begin(
                "llm",
                scope,
                model=getattr(instance, "model", ""),
                offered_tools=tool_names,
            )
            try:
                response = original_chat(
                    instance,
                    messages,
                    timeout,
                    tools=tools,
                    extra_body=extra_body,
                    retries=retries,
                )
            except Exception as exc:
                recorder.end(event_id, "error", error=f"{type(exc).__name__}: {exc}")
                raise
            else:
                calls = response.get("tool_calls") or []
                recorder.end(
                    event_id,
                    finish_reason=response.get("finish_reason", ""),
                    tool_calls=[
                        call.get("function", {}).get("name", "") for call in calls
                    ],
                    usage=response.get("usage"),
                )
                return response

        def timed_generated(instance, *, level, name, description, arguments, placeholder=None, parent_id=None):
            actual_parent = parent_id or (
                instance.current_parent_id() if level > 1 else None
            )
            event_id = recorder.begin(
                "tool",
                name,
                level=level,
                parent_id=actual_parent,
                arguments=arguments,
            )
            try:
                entry_id = original_generated(
                    instance,
                    level=level,
                    name=name,
                    description=description,
                    arguments=arguments,
                    placeholder=placeholder,
                    parent_id=parent_id,
                )
            except Exception as exc:
                recorder.end(event_id, "error", error=f"{type(exc).__name__}: {exc}")
                raise
            spans[(id(instance), entry_id)] = event_id
            return entry_id

        def timed_static_pending(instance, *, level, label, parent_id=None):
            actual_parent = parent_id or (
                instance.current_parent_id() if level > 1 else None
            )
            event_id = recorder.begin(
                "step",
                label,
                level=level,
                parent_id=actual_parent,
            )
            try:
                entry_id = original_static_pending(
                    instance, level=level, label=label, parent_id=parent_id
                )
            except Exception as exc:
                recorder.end(event_id, "error", error=f"{type(exc).__name__}: {exc}")
                raise
            spans[(id(instance), entry_id)] = event_id
            return entry_id

        def timed_resolve(instance, entry_id):
            event_id = spans.pop((id(instance), entry_id), None)
            try:
                return original_resolve(instance, entry_id)
            except Exception as exc:
                recorder.end(event_id, "error", error=f"{type(exc).__name__}: {exc}")
                raise
            finally:
                if event_id is not None:
                    recorder.end(event_id)

        self.llm_cls.chat = timed_chat
        self.notifier_cls.generated = timed_generated
        self.notifier_cls.static_pending = timed_static_pending
        self.notifier_cls.resolve = timed_resolve
        return self

    def __exit__(self, *_: Any) -> None:
        self.llm_cls.chat = self._original_chat
        self.notifier_cls.generated = self._original_generated
        self.notifier_cls.static_pending = self._original_static_pending
        self.notifier_cls.resolve = self._original_resolve


def prompt_scope(system_prompt: str) -> str:
    text = system_prompt.lower()
    patterns = [
        ("progress", "traveler-facing progress label"),
        ("orchestrator", "travel planning assistant"),
        ("explorer", "travel destination candidates"),
        ("destination_research", "research a travel destination"),
        ("weather", "only job is to call the correct weather"),
        ("transportation", "travel options for a single city-pair"),
        ("budget", "detailed trip cost breakdown"),
        ("itinerary_planner", "build a detailed day-by-day itinerary"),
        ("artifact", "compile a well-sourced travel document"),
    ]
    for scope, marker in patterns:
        if marker in text:
            return scope
    return "unknown"


def future_dates() -> tuple[str, str]:
    start = date.today() + timedelta(days=45)
    return start.isoformat(), (start + timedelta(days=9)).isoformat()


def queries(phase: int) -> list[str]:
    start, end = future_dates()
    if phase == 1:
        return [
            (
                f"Please check the weather in Tokyo from {start} through {end}. "
                "Then save one Markdown document containing only the daily weather "
                "findings, temperatures, precipitation, and dates. I am one traveler. "
                "Do not research destinations, transportation, budget, or itinerary, "
                "and do not ask me follow-up questions."
            )
        ]

    month = date.fromisoformat(start).strftime("%B %Y")
    return [
        (
            f"I am planning a 10-day trip for one traveler from Mumbai to Japan "
            f"from {start} through {end} in {month}, with a total budget of ₹250,000. "
            "I have an Indian passport. I enjoy culture, history, local food, and "
            "markets, prefer a moderate pace, and want to avoid nightlife and beach "
            "resorts. I have not chosen a destination yet. Please explore suitable "
            "destinations for these preferences and summarize the best options so I can "
            "choose. For now, do not research a specific city, calculate a full budget, "
            "build an itinerary, or save a document."
        ),
        (
            f"I have decided on Tokyo, Japan. For this trip, please now research Tokyo "
            f"thoroughly: one traveler from Mumbai, {start} through {end}, Indian passport, "
            "culture, history, local food, and markets, with a moderate pace while avoiding "
            "nightlife and beach resorts. Cover Tokyo safety, visa information for an Indian "
            "traveler, historic and food-focused neighborhoods, and suitable activities; also "
            "check the weather for the exact dates and transport from Mumbai. For transport, "
            "show the complete round trip: Mumbai city to the departure airport, both flight "
            "directions on the exact departure and return dates, and Tokyo airport transfers "
            "to the city. Do not calculate the full budget, build the itinerary, or save a "
            "document yet; I will ask for those after these findings are ready."
        ),
        (
            f"Using the Tokyo findings already gathered, please prepare the trip's detailed "
            f"budget and day-by-day plan for one traveler from Mumbai, {start} through {end}. "
            "Include accommodation, food, local transport, activities, international flight "
            "costs, and totals in both USD and INR against the ₹250,000 budget. Then build a "
            "complete moderate-pace itinerary covering culture, history, local food, and "
            "markets, with weather-aware indoor alternatives and practical assumptions. "
            "Do not save or export a document yet; I will request the final document in the "
            "next turn."
        ),
        (
            f"Everything needed for my Tokyo trip is now gathered. Please create and save one "
            f"concrete Markdown travel document for one traveler from Mumbai, {start} through "
            f"{end}, with the ₹250,000 budget and Indian passport. Include the destination "
            "options from the exploration, full Tokyo findings on safety, visa, neighborhoods, "
            "and activities, exact-date weather, the complete Mumbai-airport-flight-Tokyo "
            "round-trip transport findings, the detailed USD and INR budget, the complete "
            "day-by-day itinerary with weather alternatives, assumptions and caveats, and "
            "inline source links. Use the findings already gathered, do not ask follow-up "
            "questions, and keep the document compact with tables and bullets rather than "
            "long prose."
        ),
    ]


def safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("_") or "unknown"


def copy_artifacts(workdir: Path, trial_dir: Path) -> list[dict[str, str]]:
    destination = trial_dir / "artifacts"
    destination.mkdir(parents=True, exist_ok=True)
    copied = []
    for source in sorted(workdir.glob("*.md")):
        target = destination / source.name
        shutil.copy2(source, target)
        copied.append({"path": str(target), "name": target.name})
    return copied


def validate_artifacts(phase: int, artifacts: list[dict[str, str]]) -> tuple[dict[str, Any], list[str]]:
    texts = []
    unreadable = 0
    for artifact in artifacts:
        try:
            texts.append(Path(artifact["path"]).read_text(encoding="utf-8"))
        except OSError:
            unreadable += 1

    content = "\n".join(texts)
    validation = {
        "file_count": len(artifacts),
        "unreadable_file_count": unreadable,
        "has_findings": len(content.strip()) >= 100,
        "source_url_count": len(re.findall(r"https?://[^\\s)]+", content)),
    }
    missing = []
    if not artifacts:
        missing.append("artifact file")
    if unreadable:
        missing.append("readable artifact")
    if not validation["has_findings"]:
        missing.append("artifact findings")
    if phase == 2 and not validation["source_url_count"]:
        missing.append("artifact sources")
    return validation, missing


def knowledge_snapshot(knowledge: Any) -> dict[str, Any]:
    return {
        "candidate_count": len(knowledge.candidates),
        "research_destinations": {
            name: (item.research.depth if item.research else None)
            for name, item in knowledge.destinations.items()
        },
        "weather_destinations": {
            name: len(item.weather)
            for name, item in knowledge.destinations.items()
            if item.weather
        },
        "budget_destinations": [
            name for name, item in knowledge.destinations.items() if item.budget
        ],
        "route_count": len(knowledge.routes),
        "itinerary_count": len(knowledge.itineraries),
    }


def complete_for(
    phase: int,
    seen: set[str],
    snapshot: dict[str, Any],
    artifact_missing: list[str],
) -> tuple[bool, list[str]]:
    required = {"weather", "artifact"} if phase == 1 else ALL_SPECIALISTS
    missing = sorted(required - seen)
    missing.extend(artifact_missing)
    if phase == 1:
        if not snapshot["weather_destinations"]:
            missing.append("weather data")
    else:
        checks = {
            "candidates": snapshot["candidate_count"] > 0,
            "full research": any(value == "full" for value in snapshot["research_destinations"].values()),
            "weather data": bool(snapshot["weather_destinations"]),
            "budget data": bool(snapshot["budget_destinations"]),
            "route data": snapshot["route_count"] > 0,
            "itinerary data": snapshot["itinerary_count"] > 0,
        }
        missing.extend(name for name, present in checks.items() if not present)
    return not missing, missing


def run_trial(
    *, phase: int, attempt: int, output_root: Path, debug: bool, include_progress_llm: bool
) -> dict[str, Any]:
    # Imports happen here so --model can override Settings before it is evaluated.
    from agent.factory import build_orchestrator, create_progress_notifier
    from clients.llm_client import LLMClient
    from config.settings import settings
    from models.knowledge_state import KnowledgeState
    from notifications import ProgressNotifier
    from tools.file_write import FileWriteTool

    model = settings.llm_model
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    trial_dir = output_root / safe_name(model) / f"phase{phase}_{stamp}_attempt{attempt}"
    trial_dir.mkdir(parents=True, exist_ok=True)

    recorder = TimingRecorder()
    started_at = datetime.now(timezone.utc).isoformat()
    workdir = Path(tempfile.mkdtemp(prefix="travelagent-e2e-"))
    turn_results: list[dict[str, Any]] = []
    seen: set[str] = set()
    snapshot: dict[str, Any] = {}
    artifacts: list[dict[str, str]] = []
    artifact_validation: dict[str, Any] = {}
    complete = False
    missing: list[str] = []
    try:
        with TimingHooks(recorder, LLMClient, ProgressNotifier):
            progress = create_progress_notifier() if include_progress_llm else ProgressNotifier()
            orchestrator = build_orchestrator(
                progress=progress,
                file_write=FileWriteTool(workdir),
                debug=debug,
            )
            recorder.start_case()
            for query in queries(phase):
                turn_started = time.perf_counter()
                try:
                    response = orchestrator.turn(query)
                    turn_results.append({
                        "query": query,
                        "duration_ms": round((time.perf_counter() - turn_started) * 1000, 2),
                        "response": response,
                    })
                except Exception as exc:
                    turn_results.append({
                        "query": query,
                        "duration_ms": round((time.perf_counter() - turn_started) * 1000, 2),
                        "error": f"{type(exc).__name__}: {exc}",
                    })
                    break
            recorder.end_case()

            knowledge = orchestrator._knowledge
            snapshot = knowledge_snapshot(knowledge)
            seen = {
                event["name"]
                for event in recorder.events
                if event["kind"] == "tool" and event["name"] in ALL_SPECIALISTS
            }
            artifacts = copy_artifacts(workdir, trial_dir)
            artifact_validation, artifact_missing = validate_artifacts(phase, artifacts)
            complete, missing = complete_for(phase, seen, snapshot, artifact_missing)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    events = sorted(recorder.events, key=lambda event: event["id"])
    specialist_timing = {
        name: round(sum(event["duration_ms"] for event in events if event["kind"] == "tool" and event["name"] == name), 2)
        for name in sorted(ALL_SPECIALISTS)
        if any(event["kind"] == "tool" and event["name"] == name for event in events)
    }
    llm_timing = {}
    for event in events:
        if event["kind"] == "llm":
            llm_timing[event["name"]] = round(
                llm_timing.get(event["name"], 0) + event["duration_ms"], 2
            )

    result = {
        "phase": phase,
        "attempt": attempt,
        "model": model,
        "progress_llm_enabled": include_progress_llm,
        "started_at": started_at,
        "case_duration_ms": recorder.case_duration_ms,
        "turns": turn_results,
        "specialists_seen": sorted(seen),
        "missing": missing,
        "complete": complete,
        "knowledge": snapshot,
        "timing": {"specialists_ms": specialist_timing, "llm_ms": llm_timing},
        "events": events,
        "artifact_files": artifacts,
        "artifact_validation": artifact_validation,
        "trial_dir": str(trial_dir),
    }
    (trial_dir / "trace.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower), 2)


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    durations = [r["case_duration_ms"] for r in results if r["case_duration_ms"] is not None]
    complete_results = [r for r in results if r["complete"] and r["case_duration_ms"] is not None]
    complete_durations = [r["case_duration_ms"] for r in complete_results]

    def mean_specialist(name: str) -> float | None:
        values = [
            result["timing"]["specialists_ms"][name]
            for result in complete_results
            if name in result["timing"]["specialists_ms"]
        ]
        return round(sum(values) / len(values), 2) if values else None

    return {
        "trials": len(results),
        "complete_trials": len(complete_results),
        "completion_rate": round(len(complete_results) / len(results), 3) if results else 0.0,
        "durations_ms": durations,
        "mean_case_duration_ms": round(sum(complete_durations) / len(complete_durations), 2) if complete_durations else None,
        "mean_all_case_duration_ms": round(sum(durations) / len(durations), 2) if durations else None,
        "median_complete_case_duration_ms": round(statistics.median(complete_durations), 2) if complete_durations else None,
        "p95_complete_case_duration_ms": percentile(complete_durations, 0.95),
        "median_all_case_duration_ms": round(statistics.median(durations), 2) if durations else None,
        "p95_all_case_duration_ms": percentile(durations, 0.95),
        "mean_primary_llm_ms": round(
            sum(sum(value for scope, value in result["timing"]["llm_ms"].items() if scope != "progress") for result in complete_results) / len(complete_results), 2
        ) if complete_results else None,
        "mean_specialist_ms": {
            name: mean_specialist(name)
            for name in sorted(ALL_SPECIALISTS)
            if any(name in result["timing"]["specialists_ms"] for result in complete_results)
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Temporary TravelAgent E2E timing runner")
    parser.add_argument("--phase", type=int, choices=(1, 2), required=True)
    parser.add_argument("--attempts", type=int, default=None)
    parser.add_argument("--model", help="Override LLM_MODEL for this process")
    parser.add_argument("--debug", action="store_true", help="Enable existing agent debug output")
    parser.add_argument(
        "--include-progress-llm",
        action="store_true",
        help="Use the configured progress-label model; off by default to isolate the primary model",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "src/eval/results/e2e_timing",
    )
    args = parser.parse_args()

    if args.model:
        os.environ["LLM_MODEL"] = args.model
    attempts = args.attempts if args.attempts is not None else (1 if args.phase == 1 else 5)
    if attempts < 1 or (args.phase == 2 and attempts > 5):
        parser.error("attempts must be >= 1, and phase 2 allows at most 5")

    # Avoid timing one-time NLTK setup as part of the first case.
    from agent.factory import ensure_nltk_data
    ensure_nltk_data()

    results = []
    for attempt in range(1, attempts + 1):
        print(f"phase {args.phase}, attempt {attempt}/{attempts} ...", flush=True)
        result = run_trial(
            phase=args.phase,
            attempt=attempt,
            output_root=args.output_dir,
            debug=args.debug,
            include_progress_llm=args.include_progress_llm,
        )
        results.append(result)
        print(
            f"  {'PASS' if result['complete'] else 'INCOMPLETE'} "
            f"{result['case_duration_ms']} ms; "
            f"specialists={','.join(result['specialists_seen']) or '-'}; "
            f"missing={','.join(result['missing']) or '-'}",
            flush=True,
        )
        if result["complete"] and args.phase == 2:
            break

    model = results[0]["model"] if results else os.environ.get("LLM_MODEL", "")
    summary = {
        "phase": args.phase,
        "model": model,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "summary": summarize(results),
        "trials": [
            {
                "attempt": result["attempt"],
                "complete": result["complete"],
                "case_duration_ms": result["case_duration_ms"],
                "specialists_seen": result["specialists_seen"],
                "missing": result["missing"],
                "artifact_validation": result["artifact_validation"],
                "trial_dir": result["trial_dir"],
            }
            for result in results
        ],
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    summary_path = args.output_dir / f"phase{args.phase}_{safe_name(summary['model'])}_{stamp}.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"summary: {summary_path}")
    return 0 if all(result["complete"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
