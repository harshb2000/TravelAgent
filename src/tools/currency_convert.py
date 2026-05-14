from tools.base import BaseTool
from models.currency import CurrencyConvertOutput
from clients.currency_client import CurrencyClient


class CurrencyConvertTool(BaseTool):
    name = "currency_convert"
    description = (
        "Convert an amount from one currency to one or more target currencies in a single call. "
        "Pass all currencies you need at once — they are fetched together and cached for the session."
    )
    output_model = CurrencyConvertOutput
    parameters = {
        "type": "object",
        "properties": {
            "amount": {"type": "number", "description": "Amount to convert"},
            "from_currency": {"type": "string", "description": "ISO 4217 source currency code (e.g. USD)"},
            "to_currencies": {
                "type": "array",
                "items": {"type": "string"},
                "description": "One or more ISO 4217 target currency codes (e.g. [\"INR\", \"EUR\", \"JPY\"])",
            },
        },
        "required": ["amount", "from_currency", "to_currencies"],
    }

    def __init__(self, currency_client: CurrencyClient):
        self._client = currency_client

    def execute(self, **kwargs) -> dict:
        amount: float = float(kwargs["amount"])
        from_currency: str = kwargs["from_currency"]
        to_currencies: list[str] = kwargs["to_currencies"]

        try:
            rates = self._client.get_rates(from_currency, to_currencies)
        except Exception as e:
            return {"status": "error", "error": str(e), "fallback": ""}

        return self._validated_output({
            "from_currency": from_currency.upper(),
            "amount": amount,
            "conversions": {
                currency: {"rate": rate, "converted": round(amount * rate, 2)}
                for currency, rate in rates.items()
            },
        })
