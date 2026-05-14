from pydantic import BaseModel, Field


class ConversionResult(BaseModel):
    rate: float = Field(description="Exchange rate: 1 unit of from_currency equals this many units of the target")
    converted: float = Field(description="Converted amount rounded to 2 decimal places")


class CurrencyConvertOutput(BaseModel):
    from_currency: str = Field(description="Source currency ISO 4217 code (e.g. USD)")
    amount: float = Field(description="Original amount in from_currency")
    conversions: dict[str, ConversionResult] = Field(
        description="Keyed by target currency ISO code. Each entry has rate and converted amount."
    )
