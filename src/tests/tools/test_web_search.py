from unittest.mock import patch

from clients.search_client import SearchClient
from tools.web_search import WebSearchTool
from tests.tools.helpers import load_fixture


def test_web_search_returns_formatted_results():
    fixture = load_fixture("tavily_destination_tokyo.json")
    with patch("clients.search_client.TavilyClient") as MockTavily:
        MockTavily.return_value.search.return_value = fixture
        result = WebSearchTool(SearchClient(api_key="test-key")).execute(
            query="Tokyo travel tips 2026 daily budget", depth="advanced")
    assert "results" in result
    assert len(result["results"]) == len(fixture["results"])
    r0 = result["results"][0]
    assert r0["title"] == fixture["results"][0]["title"]
    assert r0["url"] == fixture["results"][0]["url"]
    assert r0["content"] == fixture["results"][0]["content"]
    assert r0["score"] == fixture["results"][0]["score"]


def test_web_search_includes_answer_when_present():
    fixture = load_fixture("tavily_destination_tokyo.json")
    with patch("clients.search_client.TavilyClient") as MockTavily:
        MockTavily.return_value.search.return_value = fixture
        result = WebSearchTool(SearchClient(api_key="test-key")).execute(
            query="Tokyo travel tips 2026 daily budget", depth="advanced")
    assert "answer" in result
    assert result["answer"] == fixture["answer"]


def test_web_search_call_counter_increments():
    fixture = load_fixture("tavily_visa_japan.json")
    with patch("clients.search_client.TavilyClient") as MockTavily:
        MockTavily.return_value.search.return_value = fixture
        client = SearchClient(api_key="test-key")
        tool = WebSearchTool(client)
        tool.execute(query="visa requirements Japan Indian passport 2026")
        tool.execute(query="best time to visit Tokyo weather seasons")
    assert client.call_count == 2


def test_web_search_passes_depth_and_max_results_to_client():
    fixture = load_fixture("tavily_timing_tokyo.json")
    with patch("clients.search_client.TavilyClient") as MockTavily:
        mock_search = MockTavily.return_value.search
        mock_search.return_value = fixture
        WebSearchTool(SearchClient(api_key="test-key")).execute(
            query="best time to visit Tokyo", depth="advanced", max_results=3)
    _, kwargs = mock_search.call_args
    assert kwargs.get("search_depth") == "advanced"
    assert kwargs.get("max_results") == 3
