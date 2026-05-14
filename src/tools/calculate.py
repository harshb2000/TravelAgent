import ast
from tools.base import BaseTool
from models.calculate import CalculateOutput

_ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp, ast.UnaryOp, ast.Constant,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.USub, ast.UAdd,
)


def _safe_eval(expression: str) -> float:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"Invalid expression: {e}") from e

    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ValueError(f"Disallowed operation: {type(node).__name__}")

    return float(eval(compile(tree, "<string>", "eval")))  # noqa: S307


class CalculateTool(BaseTool):
    name = "calculate"
    description = "Safely evaluate an arithmetic expression. Use for all budget arithmetic — never do mental math."
    output_model = CalculateOutput
    parameters = {
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "Arithmetic expression, e.g. '(850 * 4 + 120) / 4'"},
            "label": {"type": "string", "description": "Short label describing what is being calculated"},
        },
        "required": ["expression", "label"],
    }

    def execute(self, **kwargs) -> dict:
        expression: str = kwargs["expression"]
        label: str = kwargs["label"]

        try:
            result = _safe_eval(expression)
        except ZeroDivisionError:
            return {"status": "error", "error": "Division by zero", "fallback": ""}
        except ValueError as e:
            return {"status": "error", "error": str(e), "fallback": ""}

        return self._validated_output({"result": result, "label": label})
