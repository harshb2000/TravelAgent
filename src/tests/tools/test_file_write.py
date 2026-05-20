from tools.file_write import FileWriteTool


def test_file_write_creates_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = FileWriteTool().execute(
        filename="itinerary_tokyo_2026-06-20_v1.md", content="# Tokyo Trip\n\nDay 1...")
    assert result["status"] == "ok"
    assert (tmp_path / "itinerary_tokyo_2026-06-20_v1.md").read_text() == "# Tokyo Trip\n\nDay 1..."
    assert result["path"] == "itinerary_tokyo_2026-06-20_v1.md"


def test_file_write_increments_version_on_collision(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tool = FileWriteTool()
    tool.execute(filename="comparison_bali_2026-09_v1.md", content="first")
    result = tool.execute(filename="comparison_bali_2026-09_v1.md", content="second")
    assert result["path"] == "comparison_bali_2026-09_v2.md"
    assert (tmp_path / "comparison_bali_2026-09_v2.md").read_text() == "second"
    assert (tmp_path / "comparison_bali_2026-09_v1.md").read_text() == "first"


def test_file_write_increments_multiple_times(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tool = FileWriteTool()
    tool.execute(filename="itinerary_v1.md", content="v1")
    tool.execute(filename="itinerary_v1.md", content="v2")
    result = tool.execute(filename="itinerary_v1.md", content="v3")
    assert result["path"] == "itinerary_v3.md"
