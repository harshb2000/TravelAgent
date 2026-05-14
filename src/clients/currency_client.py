import httpx
from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Raw API model — describes what Frankfurter returns for the fields we use.
# ---------------------------------------------------------------------------

class _FrankfurterResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    base: str
    date: str
    rates: dict[str, float]


class CurrencyClient:
    def __init__(self):
        # Cache keyed by from_currency; each entry stores {to_currency: rate, ...}
        self._cache: dict[str, dict[str, float]] = {}

    def get_rates(self, from_currency: str, to_currencies: list[str]) -> dict[str, float]:
        from_key = from_currency.upper()
        to_keys = [c.upper() for c in to_currencies]

        cached = self._cache.get(from_key, {})
        missing = [c for c in to_keys if c not in cached]

        if missing:
            r = httpx.get(
                "https://api.frankfurter.app/latest",
                params={"from": from_key, "to": ",".join(missing)},
                follow_redirects=True,
                timeout=15.0,
            )
            response = _FrankfurterResponse.model_validate(r.json())
            if from_key not in self._cache:
                self._cache[from_key] = {}
            self._cache[from_key].update(response.rates)

        return {c: self._cache[from_key][c] for c in to_keys}
