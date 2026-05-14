from typing import Literal
from pydantic import BaseModel, Field


class FlightOption(BaseModel):
    airline: str = Field(description="Airline name")
    flight_number: str = Field(description="Flight number e.g. 'AI 307'")
    price_usd: float = Field(description="Combined total price for the full trip in USD")
    stops: int = Field(description="Number of stops (0 = direct flight)")
    duration_min: int = Field(description="Total flight time in minutes for this segment")
    departure: str = Field(description="Departure datetime YYYY-MM-DD HH:MM")
    arrival: str = Field(description="Arrival datetime YYYY-MM-DD HH:MM")
    origin_iata: str = Field(description="Departure airport IATA code")
    destination_iata: str = Field(description="Arrival airport IATA code")


class FlightLegResult(BaseModel):
    leg: int = Field(description="Leg number starting from 1")
    origin: str = Field(description="Comma-joined origin IATA codes as searched")
    destination: str = Field(description="Comma-joined destination IATA codes as searched")
    date: str = Field(description="Departure date YYYY-MM-DD")
    options: list[FlightOption] = Field(description="Available flights for this leg")


class FlightSearchOutput(BaseModel):
    trip_type: str = Field(description="one_way, round_trip, or multi_city")
    status: Literal["ok", "partial"] = Field(
        default="ok",
        description=(
            "'ok': all requested legs were fetched. "
            "'partial': search chain broke before all legs were retrieved — "
            "legs_fetched of legs_requested legs have results."
        ),
    )
    legs_requested: int | None = Field(
        default=None,
        description="Total legs requested. Only set when status='partial'.",
    )
    legs_fetched: int | None = Field(
        default=None,
        description="Number of legs successfully fetched. Only set when status='partial'.",
    )
    legs: list[FlightLegResult] = Field(
        description="One entry per successfully fetched leg. round_trip leg 2 options are for the first available outbound."
    )
    note: str = Field(description="Context about result generation e.g. which outbound was used to fetch return options")
