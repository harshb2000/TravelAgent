from unittest.mock import patch

from clients.currency_client import CurrencyClient
from tools.currency_convert import CurrencyConvertTool
from tests.tools.helpers import load_fixture, mock_response


def test_currency_convert_returns_correct_amounts_for_multiple_currencies():
    fixture = load_fixture("frankfurter_usd_rates.json")
    with patch("clients.currency_client.httpx.get") as mock_get:
        mock_get.return_value = mock_response(fixture)
        result = CurrencyConvertTool(CurrencyClient()).execute(
            amount=100.0, from_currency="USD", to_currencies=["INR", "EUR"])
    assert result["from_currency"] == "USD"
    assert result["amount"] == 100.0
    inr = result["conversions"]["INR"]
    eur = result["conversions"]["EUR"]
    assert inr["rate"] == fixture["rates"]["INR"]
    assert abs(inr["converted"] - 100.0 * fixture["rates"]["INR"]) < 0.01
    assert eur["rate"] == fixture["rates"]["EUR"]
    assert abs(eur["converted"] - 100.0 * fixture["rates"]["EUR"]) < 0.01


def test_currency_convert_single_http_call_for_all_requested_currencies():
    fixture = load_fixture("frankfurter_usd_rates.json")
    with patch("clients.currency_client.httpx.get") as mock_get:
        mock_get.return_value = mock_response(fixture)
        CurrencyConvertTool(CurrencyClient()).execute(
            amount=100.0, from_currency="USD", to_currencies=["INR", "EUR", "GBP", "JPY"])
    assert mock_get.call_count == 1


def test_currency_convert_cached_currencies_not_refetched():
    fixture = load_fixture("frankfurter_usd_rates.json")
    fixture_thb = {"amount": 1.0, "base": "USD", "date": fixture["date"], "rates": {"THB": 34.5}}
    with patch("clients.currency_client.httpx.get") as mock_get:
        mock_get.side_effect = [mock_response(fixture), mock_response(fixture_thb)]
        client = CurrencyClient()
        tool = CurrencyConvertTool(client)
        tool.execute(amount=100.0, from_currency="USD", to_currencies=["INR", "EUR"])
        tool.execute(amount=100.0, from_currency="USD", to_currencies=["INR", "THB"])
    assert mock_get.call_count == 2
    result = tool.execute(amount=10.0, from_currency="USD", to_currencies=["THB"])
    assert result["conversions"]["THB"]["rate"] == 34.5


def test_currency_convert_different_base_currencies_each_fetch():
    fixture_usd = load_fixture("frankfurter_usd_rates.json")
    fixture_eur = {"amount": 1.0, "base": "EUR", "date": fixture_usd["date"], "rates": {"INR": 112.0}}
    with patch("clients.currency_client.httpx.get") as mock_get:
        mock_get.side_effect = [mock_response(fixture_usd), mock_response(fixture_eur)]
        client = CurrencyClient()
        tool = CurrencyConvertTool(client)
        tool.execute(amount=100.0, from_currency="USD", to_currencies=["INR"])
        tool.execute(amount=100.0, from_currency="EUR", to_currencies=["INR"])
    assert mock_get.call_count == 2
