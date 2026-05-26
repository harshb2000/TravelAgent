from datetime import date as Date

from pydantic import BaseModel, model_validator, ValidationError

from tools.base import BaseTool
from models.flights import FlightOption, FlightLegSummary, FlightSearchOutput
from clients.serpapi_client import SerpApiClient


# ---------------------------------------------------------------------------
# Input validation model
# ---------------------------------------------------------------------------

class _FlightSearchInput(BaseModel):
    origin_airports: list[str]
    destination_airports: list[str]
    departure_date: str
    return_date: str | None = None
    adults: int = 1
    currency: str = "USD"

    @model_validator(mode="after")
    def validate_inputs(self) -> "_FlightSearchInput":
        try:
            Date.fromisoformat(self.departure_date)
        except ValueError:
            raise ValueError(
                f"Invalid departure_date format {self.departure_date!r} — expected YYYY-MM-DD"
            )
        if self.return_date is not None:
            try:
                Date.fromisoformat(self.return_date)
            except ValueError:
                raise ValueError(
                    f"Invalid return_date format {self.return_date!r} — expected YYYY-MM-DD"
                )
            if self.return_date < self.departure_date:
                raise ValueError(
                    f"return_date ({self.return_date}) must not be before departure_date ({self.departure_date})"
                )
        return self


# ---------------------------------------------------------------------------
# Top-3 selection
# ---------------------------------------------------------------------------

def _top3(flights: list[FlightOption]) -> list[FlightOption]:
    """Return up to 3 options covering min-cost, min-duration, and min-stops representatives."""
    if len(flights) <= 3:
        return list(flights)

    def _key(f: FlightOption) -> tuple:
        return (f.airline, f.flight_number, f.departure)

    selected: list[FlightOption] = []
    seen: set = set()

    def _add(f: FlightOption) -> None:
        k = _key(f)
        if k not in seen:
            seen.add(k)
            selected.append(f)

    _add(min(flights, key=lambda f: f.price_usd))       # cheapest
    _add(min(flights, key=lambda f: f.duration_min))    # fastest
    _add(min(flights, key=lambda f: f.stops))           # fewest stops
    for f in sorted(flights, key=lambda f: f.price_usd):
        if len(selected) >= 3:
            break
        _add(f)

    return selected


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

class FlightSearchTool(BaseTool):
    name = "flight_search"
    description = (
        "Search for flights using Google Flights. "
        "Returns top-3 options per leg covering cheapest, fastest, and fewest-stops. "
        "Providing return_date triggers a round-trip search; omitting it searches one-way. "
        "All prices are the combined total for the full trip in USD (round-trip price covers both directions — count once in budget)."
    )
    output_model = FlightSearchOutput
    parameters = {
        "type": "object",
        "properties": {
            "origin_airports": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Origin IATA codes, e.g. [\"BOM\"] or [\"BOM\", \"NMI\"] for multi-airport cities",
            },
            "destination_airports": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Destination IATA codes, e.g. [\"NRT\", \"HND\"] for Tokyo",
            },
            "departure_date": {
                "type": "string",
                "description": "Departure date YYYY-MM-DD",
            },
            "return_date": {
                "type": "string",
                "description": "Return date YYYY-MM-DD. Required for round_trip.",
            },
            "adults": {
                "type": "integer",
                "description": "Number of adult passengers (default 1)",
            },
            "currency": {
                "type": "string",
                "description": "ISO 4217 currency code (default USD)",
            },
        },
        "required": ["origin_airports", "destination_airports", "departure_date"],
    }

    def __init__(self, serpapi_client: SerpApiClient):
        self._client = serpapi_client

    def execute(self, **kwargs) -> dict:
        try:
            params = _FlightSearchInput(**kwargs)
        except ValidationError as e:
            return {"status": "error", "error": str(e), "fallback": ""}

        origin = params.origin_airports
        dest = params.destination_airports

        try:
            outbound_flights, return_flights = self._client.search(
                origin, dest, params.departure_date, params.return_date,
                params.adults, params.currency,
            )
            if not outbound_flights:
                return self._no_flights_error(origin, dest, params.departure_date)

            outbound_summary = FlightLegSummary(
                options=_top3(outbound_flights), total_found=len(outbound_flights)
            )

            if params.return_date is None:
                return self._validated_output({
                    "trip_type": "one_way",
                    "outbound": outbound_summary.model_dump(),
                    "note": "",
                })

            if return_flights is None:
                return self._validated_output({
                    "trip_type": "round_trip",
                    "outbound": outbound_summary.model_dump(),
                    "status": "partial",
                    "note": "Return leg options unavailable — no departure token found in outbound results.",
                })

            return_summary = FlightLegSummary(
                options=_top3(return_flights), total_found=len(return_flights)
            )
            f0 = outbound_flights[0]
            note = (
                f"Return options shown for first available outbound "
                f"({f0.airline} {f0.origin_iata}→{f0.destination_iata}, ${f0.price_usd:.0f} total)"
            )
            return self._validated_output({
                "trip_type": "round_trip",
                "outbound": outbound_summary.model_dump(),
                "return_leg": return_summary.model_dump(),
                "note": note,
            })

        except RuntimeError as e:
            msg = str(e)
            if "quota" in msg.lower() or "limit" in msg.lower():
                return {
                    "status": "error",
                    "error": msg,
                    "fallback": "Try again later or search manually at google.com/flights",
                }
            return {"status": "error", "error": msg, "fallback": ""}

    @staticmethod
    def _no_flights_error(origin: list[str], dest: list[str], date: str) -> dict:
        return {
            "status": "error",
            "error": f"No flights found for {','.join(origin)}→{','.join(dest)} on {date}",
            "fallback": "Try nearby dates or alternative airports",
        }
