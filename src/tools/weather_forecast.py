from tools.base import BaseTool
from models.weather import WeatherOutput
from clients.weather_client import WeatherClient, WMO_DESCRIPTIONS


class WeatherForecastTool(BaseTool):
    name = "weather_forecast"
    description = "Get a daily weather forecast for a city over a specific date range (up to 16 days out)."
    output_model = WeatherOutput
    parameters = {
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "City name"},
            "start_date": {"type": "string", "description": "Start date ISO 8601 (YYYY-MM-DD)"},
            "end_date": {"type": "string", "description": "End date ISO 8601 (YYYY-MM-DD)"},
        },
        "required": ["city", "start_date", "end_date"],
    }

    def __init__(self, weather_client: WeatherClient):
        self._client = weather_client

    def execute(self, **kwargs) -> dict:
        city: str = kwargs["city"]
        start_date: str = kwargs["start_date"]
        end_date: str = kwargs["end_date"]

        try:
            lat, lon, tz = self._client.geocode(city)
        except ValueError as e:
            return {"status": "error", "error": str(e), "fallback": ""}

        daily = self._client.get_forecast(lat, lon, tz, start_date, end_date)

        days = [
            {
                "date": dt,
                "temp_max": daily.temperature_2m_max[i],
                "temp_min": daily.temperature_2m_min[i],
                "precipitation_prob": daily.precipitation_probability_max[i],
                "precipitation_sum": None,
                "weather_description": WMO_DESCRIPTIONS.get(daily.weathercode[i], "Unknown"),
            }
            for i, dt in enumerate(daily.time)
        ]

        return self._validated_output({"mode": "forecast", "city": city, "days": days})
