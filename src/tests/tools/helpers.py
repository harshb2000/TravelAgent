"""Shared utilities for tool tests."""
import json
from pathlib import Path
from unittest.mock import MagicMock

FIXTURES = Path(__file__).parent.parent / "fixtures"


def load_fixture(name: str) -> dict:
    with open(FIXTURES / name) as f:
        return json.load(f)


def mock_response(data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    return resp


GEO_TOKYO = {"results": [{"latitude": 35.6895, "longitude": 139.69171, "timezone": "Asia/Tokyo"}]}
GEO_EMPTY = {"results": []}
