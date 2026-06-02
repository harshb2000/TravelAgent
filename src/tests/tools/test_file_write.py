import datetime
from unittest.mock import patch

from tools.file_write import FileWriteTool, _to_snake_case

FIXED_DATE = datetime.date(2026, 6, 2)


def _tool(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return FileWriteTool()


def test_to_snake_case():
    assert _to_snake_case("Tokyo Solo Trip") == "tokyo_solo_trip"
    assert _to_snake_case("bali-vs-portugal") == "bali_vs_portugal"
    assert _to_snake_case("  Spaces & Symbols! ") == "spaces_symbols"
    assert _to_snake_case("already_snake") == "already_snake"


def test_file_write_subject_normalised_to_snake_case(tmp_path, monkeypatch):
    tool = _tool(tmp_path, monkeypatch)
    with patch("tools.file_write.datetime") as mock_dt:
        mock_dt.date.today.return_value = FIXED_DATE
        result = tool.execute(subject="Tokyo Solo Trip", content="content")
    assert result["path"] == "tokyo_solo_trip_2026-06-02_v1.md"


def test_file_write_creates_file(tmp_path, monkeypatch):
    tool = _tool(tmp_path, monkeypatch)
    with patch("tools.file_write.datetime") as mock_dt:
        mock_dt.date.today.return_value = FIXED_DATE
        result = tool.execute(subject="tokyo_solo_trip", content="# Tokyo Trip\n\nDay 1...")
    assert result["status"] == "ok"
    assert result["path"] == "tokyo_solo_trip_2026-06-02_v1.md"
    assert (tmp_path / "tokyo_solo_trip_2026-06-02_v1.md").read_text() == "# Tokyo Trip\n\nDay 1..."


def test_file_write_increments_version_on_collision(tmp_path, monkeypatch):
    tool = _tool(tmp_path, monkeypatch)
    with patch("tools.file_write.datetime") as mock_dt:
        mock_dt.date.today.return_value = FIXED_DATE
        tool.execute(subject="comparison_bali", content="first")
        result = tool.execute(subject="comparison_bali", content="second")
    assert result["path"] == "comparison_bali_2026-06-02_v2.md"
    assert (tmp_path / "comparison_bali_2026-06-02_v2.md").read_text() == "second"
    assert (tmp_path / "comparison_bali_2026-06-02_v1.md").read_text() == "first"


def test_file_write_increments_multiple_times(tmp_path, monkeypatch):
    tool = _tool(tmp_path, monkeypatch)
    with patch("tools.file_write.datetime") as mock_dt:
        mock_dt.date.today.return_value = FIXED_DATE
        tool.execute(subject="itinerary", content="v1")
        tool.execute(subject="itinerary", content="v2")
        result = tool.execute(subject="itinerary", content="v3")
    assert result["path"] == "itinerary_2026-06-02_v3.md"
