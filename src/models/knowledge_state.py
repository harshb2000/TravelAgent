from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from typing import Literal

from pydantic import BaseModel, Field, PrivateAttr, model_validator, ConfigDict

import nltk
from nltk.corpus import stopwords
from nltk.stem import WordNetLemmatizer
from nltk.tokenize import word_tokenize


# ---------------------------------------------------------------------------
# NLTK helpers (shared by UserContext and DestinationCandidate)
# ---------------------------------------------------------------------------

_SPLIT_RE = re.compile(r"[\s\-]+")  # split on whitespace and hyphens


def _tokenize(text: str) -> frozenset[str]:
    """Lowercase, split on whitespace/hyphens, lemmatise each token."""
    return frozenset(_lemmatizer.lemmatize(t.lower()) for t in _SPLIT_RE.split(text) if t)


_NEGATION_RE = re.compile(
    r"(?:not interested in|don't want|don't|not|avoid|no|skip|except)\s+(\w+)",
    re.IGNORECASE,
)
_ISO_RANGE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})$")
_ISO_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})$")

_lemmatizer = WordNetLemmatizer()


def extract_blocklist(text: str) -> frozenset[str]:
    """Return lemmatised set of negated entities from text."""
    raw = {m.group(1).lower() for m in _NEGATION_RE.finditer(text)}
    return frozenset(_lemmatizer.lemmatize(w) for w in raw)


def build_wordset(text: str, blocklist: frozenset[str] = frozenset()) -> frozenset[str]:
    """Tokenise, remove stop words, lemmatise, exclude blocklist."""
    stop = set(stopwords.words("english"))
    tokens = word_tokenize(text.lower())
    return frozenset(
        _lemmatizer.lemmatize(t)
        for t in tokens
        if t.isalpha()
        and t not in stop
        and t not in blocklist
        and _lemmatizer.lemmatize(t) not in blocklist
    )


# ---------------------------------------------------------------------------
# DateRange
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DateRange:
    label: str
    start_date: str | None = None
    end_date: str | None = None

    @classmethod
    def from_string(cls, s: str) -> "DateRange":
        stripped = s.strip()
        m = _ISO_RANGE_RE.match(stripped)
        if m:
            return cls(label=stripped, start_date=m.group(1), end_date=m.group(2))
        m = _ISO_DATE_RE.match(stripped)
        if m:
            return cls(label=stripped, start_date=m.group(1))
        return cls(label=stripped)


# ---------------------------------------------------------------------------
# RouteKey
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RouteKey:
    origin: str
    destination: str


# ---------------------------------------------------------------------------
# Leaf models
# ---------------------------------------------------------------------------

class StringWithAttribution(BaseModel):
    text: str = Field(description="The factual claim or description text.")
    source_url: str | None = Field(default=None, description="URL of the web search result that provided this claim.")


class CostWithAttribution(BaseModel):
    amount: float = Field(description="Cost in USD.")
    source_url: str | None = Field(default=None, description="URL of the web search result that provided this cost estimate.")


class Activity(BaseModel):
    name: str = Field(description="Activity or attraction name, e.g. 'Senso-ji Temple'.")
    tags: list[str] = Field(default_factory=list, description="Category tags, e.g. ['outdoor', 'cultural', 'nightlife'].")
    indoor: bool = Field(default=False, description="True if the activity is indoors. Used for weather-aware itinerary scheduling.")
    duration_min: int | None = Field(default=None, description="Typical visit or activity duration in minutes. Null when unknown.")
    source_url: str | None = Field(default=None, description="URL of the source that described this activity.")


# ---------------------------------------------------------------------------
# DestinationResearch
# ---------------------------------------------------------------------------

class DestinationResearch(BaseModel):
    name: str = Field(description="Destination city or region name.")
    country: str = Field(description="Country the destination is in.")
    depth: Literal["light", "full"] = Field(description="Research depth. 'light': only vibe, top_attractions, and summary are expected — all other fields should be null. 'full': all fields should be populated where applicable.")
    vibe: str = Field(default="", description="1–2 sentence character sketch of the destination. Brief in light mode, richer in full mode.")
    top_attractions: list[str] = Field(default_factory=list, description="Names of notable attractions or experiences. 2–3 in light mode; expanded in full mode.")
    summary: str = Field(description="Required in both light and full mode. LLM-generated narrative that complements the structured fields — covers seasonal nuances, what makes the destination worth considering, safety context (full only), festival timing (full only), and any highlights a template cannot express.")
    visa_complexity: dict[str, StringWithAttribution] | None = Field(default=None, description="Visa info keyed by passport/profile, e.g. {'Indian passport': {text: 'e-visa $25, 3–5 days', source_url: '...'}}. Null in light mode or when nationality unknown.")
    safety_summary: StringWithAttribution | None = Field(default=None, description="Current safety assessment with source. Null in light mode.")
    festivals: list[str] | None = Field(default=None, description="Notable festivals and busy periods in the travel window that affect crowds or prices. Null in light mode.")
    neighbourhoods: dict[str, StringWithAttribution] | None = Field(default=None, description="Neighbourhood guide keyed by area name. Null in light mode.")
    activities: list[Activity] | None = Field(default=None, description="Interest-tailored activities for full-depth research. DestinationResearchSpecialist populates initial names and tags; ItineraryPlannerSpecialist later enriches with duration_min and indoor flag. Should be a non-empty list in full mode when activities are researchable; null in light mode.")


# ---------------------------------------------------------------------------
# DestinationBudget
# ---------------------------------------------------------------------------

class DestinationBudget(BaseModel):
    accommodation: dict[str, CostWithAttribution] = Field(default_factory=dict, description="Per-unit/night costs keyed by type, e.g. {'hostel dorm': {amount: 15.0}, 'mid-range hotel': {amount: 80.0}}. All amounts in USD.")
    food: dict[str, CostWithAttribution] = Field(default_factory=dict, description="Per-person/day food costs keyed by style, e.g. {'street food': {amount: 8.0}, 'sit-down restaurant': {amount: 20.0}}. All amounts in USD.")
    local_transport: dict[str, CostWithAttribution] = Field(default_factory=dict, description="Local transport costs keyed by mode, e.g. {'metro day pass': {amount: 5.0}, 'taxi 5km': {amount: 8.0}}. Per person for transit; per vehicle for taxis. All amounts in USD.")
    activities: dict[str, CostWithAttribution] = Field(default_factory=dict, description="Per-person activity costs keyed by activity, e.g. {'temple entry': {amount: 5.0}, 'guided tour': {amount: 40.0}}. All amounts in USD.")
    summary: str = Field(default="", description="LLM-generated narrative overview of the cost landscape — tier characterisation, what drives costs, value tips.")


# ---------------------------------------------------------------------------
# TravelOption
# ---------------------------------------------------------------------------

from models.flights import FlightOption  # noqa: E402


class TravelOption(BaseModel):
    mode: str = Field(description="Transport mode. Use 'flight/one-way' or 'flight/return' for flights; 'train', 'bus', 'ferry', 'taxi', 'metro' for ground/sea.")
    operator: str | None = Field(default=None, description="Carrier or operator name, e.g. 'Air India', 'Shinkansen', 'Grab'. Null when not applicable.")
    origin: str = Field(description="Granular origin, e.g. 'BOM Airport, Mumbai', 'Shinjuku Station, Tokyo', or city name for city-level transfers.")
    destination: str = Field(description="Granular destination, e.g. 'NRT Airport, Tokyo'. Match format of origin.")
    duration_min: int | None = Field(default=None, description="Travel time in minutes. Null when unknown.")
    cost_usd: float | None = Field(default=None, description="Cost in USD. For flight/return: round-trip total (count once in budget, not per leg). Null when unknown.")
    flight: FlightOption | None = Field(default=None, description="Structured flight details. Populated only for mode='flight/*'; null for all other modes.")
    source_url: str | None = Field(default=None, description="URL of the source for this option. Null for flight/* (SerpApi structured data has no single URL).")
    note: str | None = Field(default=None, description="Free-text note, e.g. booking tips, luggage restrictions, frequency.")


# ---------------------------------------------------------------------------
# Knowledge containers (plain dataclasses — use DateRange as dict key)
# ---------------------------------------------------------------------------

from models.weather import WeatherOutput  # noqa: E402


@dataclass
class DestinationKnowledge:
    research: DestinationResearch | None = None
    weather: dict = dc_field(default_factory=dict)   # DateRange -> WeatherOutput
    budget: DestinationBudget | None = None


@dataclass
class RouteKnowledge:
    options: dict = dc_field(default_factory=dict)   # DateRange -> list[TravelOption]


# ---------------------------------------------------------------------------
# Itinerary models
# ---------------------------------------------------------------------------

class TimeSlot(BaseModel):
    start_time: str = Field(description="Start time in 'HH:MM' 24-hour format, or a loose label like 'morning', 'afternoon', 'evening'.")
    activity: Activity = Field(description="The activity or transit leg for this slot.")
    location: str | None = Field(default=None, description="Specific venue or location name, e.g. 'Senso-ji Temple, Asakusa'. Null when not applicable.")
    notes: str | None = Field(default=None, description="Booking tips, access notes, opening hours caveats, or anything the traveller should know.")
    is_alternative: bool = Field(default=False, description="True when this slot is a weather-contingency alternative to the preceding non-alternative slot in the day's list. At most 2 alternatives per primary slot; at most 3 alternative slots per day total.")


class ItineraryDay(BaseModel):
    day_num: int = Field(description="1-indexed day number. Day 1 = arrival day.")
    location: str = Field(description="City or destination for this day.")
    is_arrival: bool = Field(default=False, description="True for the arrival day. Schedule should be light — orientation activities only.")
    is_departure: bool = Field(default=False, description="True for the departure day. Morning slot only; afternoon/evening left clear for travel.")
    is_transit: bool = Field(default=False, description="True for an inter-city travel day. Slots describe the transit leg with realistic travel time.")
    slots: list[TimeSlot] = Field(default_factory=list, description="Ordered time slots for the day.")
    weather_note: str | None = Field(default=None, description="Weather caveat for the day, e.g. 'Rain expected — indoor alternatives shown'. Null when weather is fine or unknown.")


class Itinerary(BaseModel):
    destinations: list[str] = Field(default_factory=list, description="Ordered list of cities/destinations. Single entry for one-city trips; multiple for multi-city routes.")
    start_date: str | None = Field(default=None, description="Arrival date in ISO format YYYY-MM-DD. Null when dates are not yet confirmed.")
    days: list[ItineraryDay] = Field(default_factory=list, description="One entry per day in trip order, starting from day 1 (arrival day).")
    notes: str | None = Field(default=None, description="Trip-level notes applicable to the whole trip, e.g. visa reminders, packing tips, currency advice.")


class ItineraryPlannerOutput(BaseModel):
    itinerary: Itinerary = Field(description="The full day-by-day itinerary.")
    activity_updates: dict[str, list[Activity]] = Field(default_factory=dict, description="Destination → enriched Activity list discovered during venue research. Empty dict if no new activities found.")


# ---------------------------------------------------------------------------
# DestinationCandidate  (wordset computed at creation via NLTK)
# ---------------------------------------------------------------------------

class DestinationCandidate(BaseModel):
    name: str = Field(description="Destination city or region name.")
    country: str = Field(description="Country the destination is in.")
    vibe_tags: list[str] = Field(default_factory=list, description="2–4 short descriptive tags capturing the destination's character, e.g. ['beach', 'budget-friendly', 'nightlife'].")
    rationale: str = Field(default="", description="One-line reason this destination matches the user's query.")
    source_url: str = Field(default="", description="URL of the web search result that surfaced this candidate.")
    query: str = Field(default="", description="The user query string that generated this candidate. Preserved so the Orchestrator can reason about relevance if intent shifts mid-session.")
    # Both fields below are system-managed — excluded from model_json_schema()
    # so the LLM never sees or sets them.
    #
    # added_at: set by the wrapper to the current turn index after construction.
    # wordset:  computed at construction from the candidate's text fields.
    _added_at: int = PrivateAttr(default=0)
    _wordset: frozenset = PrivateAttr(default_factory=frozenset)

    @model_validator(mode="after")
    def _compute_wordset(self) -> "DestinationCandidate":
        text = " ".join([self.name, self.rationale, self.query] + self.vibe_tags)
        self._wordset = build_wordset(text)
        return self

    @property
    def added_at(self) -> int:
        return self._added_at

    @added_at.setter
    def added_at(self, value: int) -> None:
        self._added_at = value

    @property
    def wordset(self) -> frozenset:
        return self._wordset

    def should_exclude(self, blocklist: frozenset[str]) -> bool:
        """
        Hard-exclude if name or country contains a blocklisted term (identity signal).
        Soft-exclude on tags only when blocked tags strictly outnumber unblocked ones —
        a single blocked tag among several positive ones is handled by Jaccard scoring instead.
        """
        if not blocklist:
            return False
        # Hard: name or country token matches → this IS the blocked place
        if (_tokenize(self.name) | _tokenize(self.country)) & blocklist:
            return True
        # Soft: tag majority — exclude only when more tags are blocked than unblocked
        blocked = sum(1 for tag in self.vibe_tags if _tokenize(tag) & blocklist)
        return blocked > (len(self.vibe_tags) - blocked)


# ---------------------------------------------------------------------------
# UserContext
# ---------------------------------------------------------------------------

class UserContext:
    def __init__(self, context: str = ""):
        self._context = ""
        self.wordset: frozenset[str] = frozenset()
        self.blocklist: frozenset[str] = frozenset()
        if context:
            self.context = context

    @property
    def context(self) -> str:
        return self._context

    @context.setter
    def context(self, value: str) -> None:
        self._context = value
        self._recompute()

    def _recompute(self) -> None:
        text = self._context
        self.blocklist = extract_blocklist(text)
        self.wordset = build_wordset(text, self.blocklist)


# ---------------------------------------------------------------------------
# KnowledgeState
# ---------------------------------------------------------------------------

ALPHA = 0.3
TOP_N_CANDIDATES = 5


class KnowledgeState:
    def __init__(self) -> None:
        self.candidates: list[DestinationCandidate] = []
        self.destinations: dict[str, DestinationKnowledge] = {}
        self.routes: dict[RouteKey, RouteKnowledge] = {}
        self.itineraries: dict[frozenset, Itinerary] = {}

    # ---- write methods ----

    def add_candidates(self, results: list[DestinationCandidate]) -> None:
        self.candidates.extend(results)

    def update_research(self, destination: str, result: DestinationResearch) -> None:
        self._ensure_destination(destination).research = result

    def update_weather(
        self, destination: str, date_range: DateRange, result: WeatherOutput
    ) -> None:
        self._ensure_destination(destination).weather[date_range] = result

    def update_route(
        self,
        origin: str,
        destination: str,
        date_range: DateRange,
        options: list[TravelOption],
    ) -> None:
        rk = RouteKey(origin, destination)
        if rk not in self.routes:
            self.routes[rk] = RouteKnowledge()
        self.routes[rk].options[date_range] = options

    def update_destination_budget(
        self, destination: str, result: DestinationBudget
    ) -> None:
        dk = self._ensure_destination(destination)
        if dk.budget is None:
            dk.budget = result
            return
        # Merge each cost category so previously fetched entries are not lost.
        # New keys are added; existing keys are overwritten with fresher data.
        dk.budget.accommodation.update(result.accommodation)
        dk.budget.food.update(result.food)
        dk.budget.local_transport.update(result.local_transport)
        dk.budget.activities.update(result.activities)
        if result.summary:
            dk.budget.summary = result.summary

    def update_activities(
        self, destination: str, activities: list[Activity]
    ) -> None:
        dk = self._ensure_destination(destination)
        if dk.research is None:
            return
        if not dk.research.activities:
            dk.research.activities = list(activities)
            return
        # Merge by name: enrich existing entries, append genuinely new ones.
        by_name = {a.name: a for a in dk.research.activities}
        for incoming in activities:
            if incoming.name in by_name:
                existing = by_name[incoming.name]
                if incoming.tags:
                    existing.tags = incoming.tags
                # ItineraryPlanner's indoor judgment is authoritative — always take it
                existing.indoor = incoming.indoor
                if incoming.duration_min is not None:
                    existing.duration_min = incoming.duration_min
                if incoming.source_url is not None:
                    existing.source_url = incoming.source_url
            else:
                by_name[incoming.name] = incoming
                dk.research.activities.append(incoming)

    def update_itinerary(self, destinations: frozenset, itinerary: Itinerary) -> None:
        self.itineraries[destinations] = itinerary

    # ---- read methods ----

    def to_prompt_context(
        self,
        user_context: "UserContext | None" = None,
        top_n: int = TOP_N_CANDIDATES,
    ) -> str:
        sections: list[str] = []

        # CANDIDATES section
        if self.candidates:
            candidates = list(self.candidates)
            n_total = len(candidates)

            if user_context is not None and candidates:
                uc_ws = user_context.wordset
                current_turn = max(c.added_at for c in candidates)

                raw_rec = [1.0 / (current_turn - c.added_at + 1) for c in candidates]
                raw_jac = [
                    (len(c.wordset & uc_ws) / len(c.wordset | uc_ws))
                    if (c.wordset | uc_ws)
                    else 0.0
                    for c in candidates
                ]

                max_r = max(raw_rec) or 1.0
                max_j = max(raw_jac) or 0.0

                norm_r = [r / max_r for r in raw_rec]
                norm_j = [j / max_j if max_j > 0 else 0.0 for j in raw_jac]

                scores = [ALPHA * nr + (1 - ALPHA) * nj for nr, nj in zip(norm_r, norm_j)]
                ranked = sorted(enumerate(scores), key=lambda x: -x[1])
                top = [candidates[i] for i, _ in ranked[:top_n]]
            else:
                top = sorted(candidates, key=lambda c: -c.added_at)[:top_n]

            n_showing = len(top)
            header = (
                f"CANDIDATES (showing {n_showing} of {n_total}):"
                if n_total > top_n
                else f"CANDIDATES ({n_showing}):"
            )
            lines = [header]
            for c in top:
                tags = ", ".join(c.vibe_tags) if c.vibe_tags else "—"
                lines.append(f'  {c.name} ({c.country}) [{tags} · "{c.query}"]')
            sections.append("\n".join(lines))

        # DESTINATIONS section
        if self.destinations:
            lines = ["DESTINATIONS"]
            for name, dk in self.destinations.items():
                depth = dk.research.depth if dk.research else "—"
                lines.append(f"  {name}  [{depth}]")
                if dk.weather:
                    for dr, wo in dk.weather.items():
                        lines.append(f"    weather ({dr.label}): ✓ ({wo.mode})")
                else:
                    lines.append("    weather: —")
                if dk.budget:
                    cats = [
                        dk.budget.accommodation,
                        dk.budget.food,
                        dk.budget.local_transport,
                        dk.budget.activities,
                    ]
                    try:
                        low = sum(
                            min(v.amount for v in cat.values()) for cat in cats if cat
                        )
                        high = sum(
                            max(v.amount for v in cat.values()) for cat in cats if cat
                        )
                        lines.append(f"    destination budget: ~${low:.0f}–${high:.0f}/day")
                    except (ValueError, AttributeError):
                        lines.append("    destination budget: ✓")
                else:
                    lines.append("    destination budget: —")
            sections.append("\n".join(lines))

        # ROUTES section
        if self.routes:
            lines = ["ROUTES"]
            for rk, rk_knowledge in self.routes.items():
                for dr, opts in rk_knowledge.options.items():
                    flight_opts = [
                        o for o in opts if "flight" in o.mode and o.cost_usd is not None
                    ]
                    if flight_opts:
                        min_cost = min(o.cost_usd for o in flight_opts)
                        lines.append(
                            f"  {rk.origin} → {rk.destination} ({dr.label}): ✓ from ${min_cost:.0f}"
                        )
                    elif opts:
                        lines.append(f"  {rk.origin} → {rk.destination} ({dr.label}): ✓")
            sections.append("\n".join(lines))

        return "\n\n".join(sections) if sections else "(no information collected yet)"

    # ---- internal helpers ----

    def _ensure_destination(self, name: str) -> DestinationKnowledge:
        if name not in self.destinations:
            self.destinations[name] = DestinationKnowledge()
        return self.destinations[name]
