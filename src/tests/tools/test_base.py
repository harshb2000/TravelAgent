from tools.base import BaseTool
from tools.calculate import CalculateTool
from clients.weather_client import WeatherClient


def test_tool_output_model_schema_appended_to_llm_definition():
    defn = CalculateTool().to_llm_definition()
    desc = defn["function"]["description"]
    assert "Success output schema:" in desc
    assert "result" in desc
    assert "label" in desc


def test_tool_without_output_model_has_clean_description():
    class _Bare(BaseTool):
        name = "bare"
        description = "A bare tool."
        parameters = {"type": "object", "properties": {}, "required": []}
        def execute(self, **kwargs): return {}
    assert "Success output schema:" not in _Bare().to_llm_definition()["function"]["description"]
