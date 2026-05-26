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


class FlightLegSummary(BaseModel):
    options: list[FlightOption] = Field(
        description="Top-3 options covering min-cost, min-duration, and min-stops representatives"
    )
    total_found: int = Field(description="Total number of flights found before top-3 selection")


class FlightSearchOutput(BaseModel):
    trip_type: Literal["one_way", "round_trip"] = Field(description="one_way or round_trip")
    outbound: FlightLegSummary = Field(description="Outbound leg summary with top-3 options")
    return_leg: FlightLegSummary | None = Field(
        default=None,
        description="Return leg summary. None for one_way or when departure token unavailable.",
    )
    status: Literal["ok", "partial"] = Field(
        default="ok",
        description="'ok': all legs fetched. 'partial': return leg unavailable (no flights available).",
    )
    note: str = Field(default="", description="Context about result generation")
