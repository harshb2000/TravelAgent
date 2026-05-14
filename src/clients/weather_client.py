import calendar
from datetime import date

import httpx
from pydantic import BaseModel, ConfigDict

from models.weather import DailyWeather, WeatherOutput  # noqa: F401 — re-exported for convenience


# ---------------------------------------------------------------------------
# Raw API models — describe exactly what Open-Meteo returns for the fields we use.
# Changes to the API surface as ValidationError here, not as KeyError downstream.
# ---------------------------------------------------------------------------

class _GeocodingResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    latitude: float
    longitude: float
    timezone: str


class _GeocodingResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    results: list[_GeocodingResult] = []


class _ForecastDaily(BaseModel):
    model_config = ConfigDict(extra="ignore")
    time: list[str]
    temperature_2m_max: list[float]
    temperature_2m_min: list[float]
    precipitation_probability_max: list[int]
    weathercode: list[int]


class _ForecastResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    daily: _ForecastDaily


class _ClimateDaily(BaseModel):
    model_config = ConfigDict(extra="ignore")
    time: list[str]
    temperature_2m_max: list[float]
    temperature_2m_min: list[float]
    precipitation_sum: list[float]


class _ClimateResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    daily: _ClimateDaily


# ---------------------------------------------------------------------------
# WMO weather code → description
# Source: https://open-meteo.com/en/docs — "WMO Weather interpretation codes (WW)"
# ---------------------------------------------------------------------------

WMO_DESCRIPTIONS: dict[int, str] = {
    0:  "Clear sky",
    1:  "Mainly clear",
    2:  "Partly cloudy",
    3:  "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Drizzle: light",
    53: "Drizzle: moderate",
    55: "Drizzle: dense",
    56: "Freezing drizzle: light",
    57: "Freezing drizzle: heavy",
    61: "Rain: slight",
    63: "Rain: moderate",
    65: "Rain: heavy",
    66: "Freezing rain: light",
    67: "Freezing rain: heavy",
    71: "Snow: slight",
    73: "Snow: moderate",
    75: "Snow: heavy",
    77: "Snow grains",
    80: "Rain showers: slight",
    81: "Rain showers: moderate",
    82: "Rain showers: violent",
    85: "Snow showers: slight",
    86: "Snow showers: heavy",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def _parse_month(month: str | int) -> int:
    if isinstance(month, int):
        return month
    try:
        return int(month)
    except ValueError:
        names = [m.lower() for m in calendar.month_name]
        return names.index(month.strip().lower())


def _month_to_date_range(month: str | int, year: int | None = None) -> tuple[str, str]:
    month_num = _parse_month(month)
    if year is None:
        today = date.today()
        year = today.year if month_num >= today.month else today.year + 1
    last_day = calendar.monthrange(year, month_num)[1]
    return f"{year}-{month_num:02d}-01", f"{year}-{month_num:02d}-{last_day:02d}"


class WeatherClient:
    def __init__(self):
        self._geo_cache: dict[str, tuple[float, float, str]] = {}

    def geocode(self, city: str) -> tuple[float, float, str]:
        key = city.lower()
        if key in self._geo_cache:
            return self._geo_cache[key]

        r = httpx.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1, "language": "en", "format": "json"},
            timeout=15.0,
        )
        response = _GeocodingResponse.model_validate(r.json())
        if not response.results:
            raise ValueError(f"Geocoding: city not found — {city!r}")

        result = response.results[0]
        coords = (result.latitude, result.longitude, result.timezone)
        self._geo_cache[key] = coords
        return coords

    def get_forecast(self, lat: float, lon: float, timezone: str, start_date: str, end_date: str) -> _ForecastDaily:
        r = httpx.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode",
                "timezone": timezone,
                "start_date": start_date,
                "end_date": end_date,
            },
            timeout=15.0,
        )
        return _ForecastResponse.model_validate(r.json()).daily

    def get_climate_average(self, lat: float, lon: float, start_date: str, end_date: str) -> _ClimateDaily:
        r = httpx.get(
            "https://climate-api.open-meteo.com/v1/climate",
            params={
                "latitude": lat,
                "longitude": lon,
                "start_date": start_date,
                "end_date": end_date,
                "models": "EC_Earth3P_HR",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
            },
            timeout=15.0,
        )
        return _ClimateResponse.model_validate(r.json()).daily
