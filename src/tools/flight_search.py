from datetime import date as Date
from typing import Literal

from pydantic import BaseModel, model_validator
from pydantic import ValidationError

from tools.base import BaseTool
from models.flights import FlightOption, FlightSearchOutput
from clients.serpapi_client import SerpApiClient


# ---------------------------------------------------------------------------
# Input validation model
# ---------------------------------------------------------------------------

class _Leg(BaseModel):
    origin_airports: list[str]
    destination_airports: list[str]
    date: str

    @model_validator(mode="after")
    def validate_date_format(self) -> "_Leg":
        try:
            Date.fromisoformat(self.date)
        except ValueError:
            raise ValueError(f"Invalid date format {self.date!r} — expected YYYY-MM-DD")
        return self


class _FlightSearchInput(BaseModel):
    trip_type: Literal["one_way", "round_trip", "multi_city"]
    legs: list[_Leg]
    adults: int = 1
    currency: str = "USD"

    @model_validator(mode="after")
    def validate_legs(self) -> "_FlightSearchInput":
        n = len(self.legs)
        if self.trip_type == "one_way" and n != 1:
            raise ValueError(f"one_way requires exactly 1 leg, got {n}")
        if self.trip_type == "round_trip" and n != 2:
            raise ValueError(f"round_trip requires exactly 2 legs, got {n}")
        if self.trip_type == "multi_city" and n < 2:
            raise ValueError(f"multi_city requires at least 2 legs, got {n}")

        for i in range(1, n):
            if self.legs[i].date <= self.legs[i - 1].date:
                raise ValueError(
                    f"Leg {i + 1} date ({self.legs[i].date}) must be after "
                    f"leg {i} date ({self.legs[i - 1].date})"
                )
        return self


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

_LEG_SCHEMA = {
    "type": "object",
    "properties": {
        "origin_airports":      {"type": "array", "items": {"type": "string"}, "description": "IATA codes, e.g. [\"BOM\"] or [\"BOM\", \"NMI\"]"},
        "destination_airports": {"type": "array", "items": {"type": "string"}, "description": "IATA codes, e.g. [\"NRT\", \"HND\"] for Tokyo"},
        "date":                 {"type": "string", "description": "YYYY-MM-DD"},
    },
    "required": ["origin_airports", "destination_airports", "date"],
}




class FlightSearchTool(BaseTool):
    name = "flight_search"
    description = (
        "Search for flights using Google Flights. "
        "Always provide trip_type and legs — legs carries all routing for every trip type: "
        "one_way = 1 leg, round_trip = 2 legs, multi_city = N legs in order. "
        "Every leg requires origin_airports, destination_airports, and date. "
        "All prices returned are the combined total for the full trip. "
        "Output status may be 'partial' when the search chain could not be completed — "
        "legs_requested and legs_fetched indicate how many legs were attempted vs retrieved."
    )
    output_model = FlightSearchOutput
    parameters = {
        "type": "object",
        "properties": {
            "trip_type": {
                "type": "string",
                "enum": ["one_way", "round_trip", "multi_city"],
                "description": "one_way: 1 leg. round_trip: 2 legs (outbound + return). multi_city: N legs.",
            },
            "legs": {
                "type": "array",
                "items": _LEG_SCHEMA,
                "description": "Ordered legs, each with origin_airports, destination_airports, and date.",
            },
            "adults":   {"type": "integer", "description": "Number of adult passengers (default 1)"},
            "currency": {"type": "string",  "description": "ISO 4217 currency code (default USD)"},
        },
        "required": ["trip_type", "legs"],
    }

    def __init__(self, serpapi_client: SerpApiClient):
        self._client = serpapi_client

    def execute(self, **kwargs) -> dict:
        try:
            params = _FlightSearchInput(**kwargs)
        except ValidationError as e:
            return {"status": "error", "error": str(e), "fallback": ""}

        legs = [leg.model_dump() for leg in params.legs]

        try:
            if params.trip_type == "one_way":
                flights = self._client.search_one_way(legs[0], params.adults, params.currency)
                if not flights:
                    return self._no_flights_error(legs[0])
                return self._validated_output(
                    {"trip_type": "one_way", "legs": [self._leg_result(1, legs[0], flights)], "note": ""}
                )

            elif params.trip_type == "round_trip":
                outbound, returns = self._client.search_round_trip(legs[0], legs[1]["date"], params.adults, params.currency)
                if not outbound:
                    return self._no_flights_error(legs[0])
                if returns is None:
                    # Outbound fetched but no valid departure_token found — can't retrieve return options
                    return self._validated_output({
                        "trip_type": "round_trip",
                        "status": "partial",
                        "legs_requested": 2,
                        "legs_fetched": 1,
                        "legs": [self._leg_result(1, legs[0], outbound)],
                        "note": "Return leg options unavailable — no departure token found in outbound results.",
                    })
                note = (f"Return options shown for first available outbound "
                        f"({outbound[0].airline} {outbound[0].origin_iata}→{outbound[0].destination_iata}, "
                        f"${outbound[0].price_usd:.0f} total)")
                # legs[1].origin_airports / destination_airports are intentionally ignored.
                # The API requires the same airport pool as the outbound for the return call
                # (confirmed by testing — changing airports causes no-result errors).
                # We reconstruct the canonical return leg def from the outbound for display purposes only.
                return_leg_def = {
                    "origin_airports":      legs[0]["destination_airports"],
                    "destination_airports": legs[0]["origin_airports"],
                    "date": legs[1]["date"],
                }
                result_legs = [
                    self._leg_result(1, legs[0], outbound),
                    self._leg_result(2, return_leg_def, returns),
                ]
                return self._validated_output({"trip_type": "round_trip", "legs": result_legs, "note": note})

            else:  # multi_city
                per_leg = self._client.search_multi_city(legs, params.adults, params.currency)
                result_legs = [self._leg_result(i + 1, leg_def, options)
                               for i, (leg_def, options) in enumerate(zip(legs, per_leg))]
                if not result_legs or not any(leg["options"] for leg in result_legs):
                    return {"status": "error", "error": "No flights found for any leg", "fallback": "Try different dates or airports"}

                note = "Leg 2+ options shown for first available leg 1 result"
                if per_leg[0]:
                    f0 = per_leg[0][0]
                    note = (f"Leg 2+ options shown for first available leg 1 result "
                            f"({f0.airline} {f0.origin_iata}→{f0.destination_iata}, ${f0.price_usd:.0f} total)")

                legs_fetched = len(per_leg)
                legs_requested = len(legs)
                if legs_fetched < legs_requested:
                    return self._validated_output({
                        "trip_type": "multi_city",
                        "status": "partial",
                        "legs_requested": legs_requested,
                        "legs_fetched": legs_fetched,
                        "legs": result_legs,
                        "note": (f"{note}. Search incomplete: could not fetch leg "
                                 f"{legs_fetched + 1} — no departure token available from leg {legs_fetched} results."),
                    })

                return self._validated_output({"trip_type": "multi_city", "legs": result_legs, "note": note})

        except RuntimeError as e:
            msg = str(e)
            if "quota" in msg.lower() or "limit" in msg.lower():
                return {"status": "error", "error": msg, "fallback": "Try again later or search manually at google.com/flights"}
            return {"status": "error", "error": msg, "fallback": ""}

    @staticmethod
    def _leg_result(leg_num: int, leg_def: dict, flights: list[FlightOption]) -> dict:
        return {
            "leg": leg_num,
            "origin":      ",".join(leg_def["origin_airports"]),
            "destination": ",".join(leg_def["destination_airports"]),
            "date":        leg_def["date"],
            "options":     [f.model_dump() for f in flights],
        }

    @staticmethod
    def _no_flights_error(leg: dict) -> dict:
        origin = ",".join(leg["origin_airports"])
        dest   = ",".join(leg["destination_airports"])
        return {
            "status": "error",
            "error": f"No flights found for {origin}→{dest} on {leg['date']}",
            "fallback": "Try nearby dates or alternative airports",
        }
