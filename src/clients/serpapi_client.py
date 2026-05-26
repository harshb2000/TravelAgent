import httpx
from pydantic import BaseModel, ConfigDict

from models.flights import FlightOption


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

    def search(
        self,
        origin_airports: list[str],
        destination_airports: list[str],
        departure_date: str,
        return_date: str | None = None,
        adults: int = 1,
        currency: str = "USD",
    ) -> tuple[list[FlightOption], list[FlightOption] | None]:
        """
        Returns (outbound_options, return_options).
        return_options is None for one-way, or when no departure_token is available for the return leg.
        The return call reuses the same departure_id/arrival_id pool (changing these causes no-result errors).
        """
        base_params = {
            "engine": "google_flights",
            "type": "1" if return_date else "2",
            "departure_id":  ",".join(origin_airports),
            "arrival_id":    ",".join(destination_airports),
            "outbound_date": departure_date,
            "adults": str(adults),
        }
        if return_date:
            base_params["return_date"] = return_date

        outbound_response = self._get({**base_params, "currency": currency})
        outbound = _extract_priced_flights(outbound_response)

        if not return_date:
            return outbound, None

        if not outbound:
            return [], None

        token = _first_departure_token(outbound_response)
        if not token:
            return outbound, None  # outbound found but no departure_token for return leg

        return_response = self._get({**base_params, "departure_token": token, "currency": currency})
        return outbound, _extract_priced_flights(return_response)

