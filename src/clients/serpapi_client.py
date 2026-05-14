import json
import httpx
from pydantic import BaseModel, ConfigDict

from models.flights import FlightOption

TRIP_TYPE_MAP = {
    "one_way":    "2",
    "round_trip": "1",
    "multi_city": "3",
}


# ---------------------------------------------------------------------------
# Raw API models — describe exactly what SerpApi returns for the fields we use.
# ---------------------------------------------------------------------------

class _RawAirport(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    time: str


class _RawSegment(BaseModel):
    model_config = ConfigDict(extra="ignore")
    departure_airport: _RawAirport
    arrival_airport: _RawAirport
    airline: str
    flight_number: str
    duration: int


class _RawFlightResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    flights: list[_RawSegment]
    total_duration: int
    price: float | None = None          # absent on some other_flights entries
    departure_token: str | None = None  # present on non-terminal legs


class _RawFlightSearchResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    best_flights: list[_RawFlightResult] = []
    other_flights: list[_RawFlightResult] = []


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def _extract_flight_details(raw: _RawFlightResult) -> FlightOption:
    segs = raw.flights
    return FlightOption(
        airline=segs[0].airline,
        flight_number=segs[0].flight_number,
        price_usd=float(raw.price),  # type: ignore[arg-type]  # only called when price is not None
        stops=len(segs) - 1,
        duration_min=raw.total_duration,
        departure=segs[0].departure_airport.time,
        arrival=segs[-1].arrival_airport.time,
        origin_iata=segs[0].departure_airport.id,
        destination_iata=segs[-1].arrival_airport.id,
    )


def _extract_priced_flights(response: _RawFlightSearchResponse) -> list[FlightOption]:
    """Return FlightOption for every result that has a price; silently ignore priceless entries."""
    all_results = response.best_flights + response.other_flights
    return [_extract_flight_details(f) for f in all_results if f.price is not None]


def _first_departure_token(response: _RawFlightSearchResponse) -> str | None:
    """Return the departure_token from the first priced result that has a non-empty token."""
    for f in response.best_flights + response.other_flights:
        if f.price is not None and f.departure_token:
            return f.departure_token
    return None


class SerpApiClient:
    BASE_URL = "https://serpapi.com/search"

    def __init__(self, api_key: str):
        self._api_key = api_key

    def _get(self, params: dict) -> _RawFlightSearchResponse:
        r = httpx.get(
            self.BASE_URL,
            params={**params, "api_key": self._api_key, "hl": "en", "currency": params.pop("currency", "USD")},
            timeout=30.0,
        )
        if r.status_code == 429:
            raise RuntimeError("Flight search quota exceeded — monthly SerpApi limit reached")
        if r.status_code != 200:
            raise RuntimeError(f"SerpApi error ({r.status_code}): {r.text[:200]}")
        return _RawFlightSearchResponse.model_validate(r.json())

    def search_one_way(self, leg: dict, adults: int = 1, currency: str = "USD") -> list[FlightOption]:
        response = self._get({
            "engine": "google_flights", "type": "2",
            "departure_id": ",".join(leg["origin_airports"]),
            "arrival_id":   ",".join(leg["destination_airports"]),
            "outbound_date": leg["date"],
            "adults": str(adults), "currency": currency,
        })
        return _extract_priced_flights(response)

    def search_round_trip(
        self, outbound_leg: dict, return_date: str, adults: int = 1, currency: str = "USD"
    ) -> tuple[list[FlightOption], list[FlightOption] | None]:
        """
        Returns (outbound_options, return_options_for_first_available_outbound).
        Returns None for return_options when no valid departure_token is available from outbound results.
        Only the outbound_leg airports define the route — the return call must reuse the same
        departure_id/arrival_id pool (confirmed by API testing: changing these causes no-result errors).
        """
        base_params = {
            "engine": "google_flights", "type": "1",
            "departure_id":  ",".join(outbound_leg["origin_airports"]),
            "arrival_id":    ",".join(outbound_leg["destination_airports"]),
            "outbound_date": outbound_leg["date"],
            "return_date":   return_date,
            "adults": str(adults),
        }
        outbound_response = self._get({**base_params, "currency": currency})
        outbound = _extract_priced_flights(outbound_response)

        if not outbound:
            return [], None

        token = _first_departure_token(outbound_response)
        if not token:
            return outbound, None  # outbound found but no valid departure_token for return leg

        return_response = self._get({**base_params, "departure_token": token, "currency": currency})
        return outbound, _extract_priced_flights(return_response)

    def search_multi_city(self, legs: list[dict], adults: int = 1, currency: str = "USD") -> list[list[FlightOption]]:
        """
        Returns one option-list per leg, chained from the first available prior leg's departure_token.
        May return fewer lists than len(legs) if the chain breaks (no token available for the next leg).
        The caller is responsible for detecting and surfacing a partial result.
        """
        mc_legs = [
            {"departure_id": ",".join(leg["origin_airports"]),
             "arrival_id":   ",".join(leg["destination_airports"]),
             "date":          leg["date"]}
            for leg in legs
        ]
        base_params = {
            "engine": "google_flights", "type": "3",
            "multi_city_json": json.dumps(mc_legs),
            "adults": str(adults),
        }

        first_response = self._get({**base_params, "currency": currency})
        all_legs: list[list[FlightOption]] = [_extract_priced_flights(first_response)]
        last_response = first_response

        for _ in legs[1:]:
            token = _first_departure_token(last_response)
            if not token:
                break  # Chain broken — no token available for the next leg; remaining legs unfetchable
            last_response = self._get({**base_params, "departure_token": token, "currency": currency})
            all_legs.append(_extract_priced_flights(last_response))

        return all_legs
