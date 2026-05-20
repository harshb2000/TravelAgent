from tools.calculate import CalculateTool


def test_calculate_basic_expression():
    result = CalculateTool().execute(expression="(850 * 4 + 120) / 4", label="per-person flight")
    assert result["result"] == 880.0
    assert result["label"] == "per-person flight"


def test_calculate_multi_operator_with_parentheses():
    assert CalculateTool().execute(expression="(100 + 200) * 3 - 50 / 2", label="test")["result"] == 875.0


def test_calculate_rejects_function_call():
    assert CalculateTool().execute(expression="sqrt(4)", label="bad")["status"] == "error"


def test_calculate_rejects_attribute_access():
    assert CalculateTool().execute(expression="os.getcwd()", label="bad")["status"] == "error"


def test_calculate_division_by_zero():
    assert CalculateTool().execute(expression="10 / 0", label="div zero")["status"] == "error"


def test_calculate_unary_minus():
    assert CalculateTool().execute(expression="-5 * 3", label="unary")["result"] == -15.0
