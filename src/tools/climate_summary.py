from tools.base import BaseTool
from models.weather import WeatherOutput
from clients.weather_client import WeatherClient, _month_to_date_range


class ClimateSummaryTool(BaseTool):
    name = "climate_summary"
    description = (
        "Get historical climate averages for a city for a given month "
        "(use for trips more than 16 days out or when only a month is known). "
        "Output is a historical average, not a live forecast — label it as such when presenting to the user."
    )
    output_model = WeatherOutput
    parameters = {
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "City name"},
            "month": {"type": "string", "description": "Month name or number (e.g. 'June' or '6')"},
            "year": {"type": "integer", "description": "Year (e.g. 2026); defaults to next occurrence of the month"},
        },
        "required": ["city", "month"],
    }

    def __init__(self, weather_client: WeatherClient):
        self._client = weather_client

    def execute(self, **kwargs) -> dict:
        city: str = kwargs["city"]
        month: str = kwargs["month"]
        year: int | None = kwargs.get("year")

        try:
            lat, lon, _ = self._client.geocode(city)
        except ValueError as e:
            return {"status": "error", "error": str(e), "fallback": ""}

        start_date, end_date = _month_to_date_range(month, year)
        daily = self._client.get_climate_average(lat, lon, start_date, end_date)

        days = [
            {
                "date": dt,
                "temp_max": daily.temperature_2m_max[i],
                "temp_min": daily.temperature_2m_min[i],
                "precipitation_prob": None,
                "precipitation_sum": daily.precipitation_sum[i],
                "weather_description": "",
            }
            for i, dt in enumerate(daily.time)
        ]

        return self._validated_output({"mode": "climate", "city": city, "days": days})
