from typing import Literal
from pydantic import BaseModel, Field


class DailyWeather(BaseModel):
    date: str = Field(description="Date YYYY-MM-DD.")
    temp_max: float = Field(description="Maximum temperature in °C for the day.")
    temp_min: float = Field(description="Minimum temperature in °C for the day.")
    precipitation_prob: int | None = Field(
        description="Precipitation probability 0–100%. Populated in forecast mode only; null in climate mode."
    )
    precipitation_sum: float | None = Field(
        description="Precipitation in mm. Historical daily average in climate mode; null in forecast mode."
    )
    weather_description: str = Field(
        description="WMO weather condition description, e.g. 'Rain: moderate', 'Partly cloudy'. Empty string in climate mode — use precipitation_sum instead."
    )


class WeatherOutput(BaseModel):
    mode: Literal["forecast", "climate"] = Field(
        description="'forecast': live prediction up to 16 days ahead. 'climate': 30-year historical monthly average."
    )
    city: str = Field(description="City name exactly as provided to the tool.")
    days: list[DailyWeather] = Field(
        description="Per-day weather data. Forecast: one entry per requested day. Climate: one entry per calendar day of the month."
    )
