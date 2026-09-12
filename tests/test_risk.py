"""
Tests for Risk & Blast Radius Agent.
"""

from sentinel.agents.risk import compute_symbol_cyclomatic_complexity, evaluate_pr_risk
from sentinel.state import ASTSymbolScope, FindingCategory, RiskLevel, Severity, TrustZone


def test_compute_cyclomatic_complexity():
    code = """def complex_function(a, b, c):
    if a > 0:
        for i in range(b):
            if i % 2 == 0 and c:
                return i
    elif b < 0:
        return -1
    return 0
"""
    symbol = ASTSymbolScope(
        symbol_name="complex_function",
        symbol_type="function",
        file_path="services/calc.py",
        start_line=1,
        end_line=9,
        code_snippet=code,
    )
    complexity = compute_symbol_cyclomatic_complexity(symbol)
    # Expected branches: base (1) + if (1) + for (1) + if (1) + and (1) + elif (1) = 6
    assert complexity >= 5


def test_evaluate_pr_risk_untested_perimeter_flagged():
    symbol = ASTSymbolScope(
        symbol_name="handle_webhook",
        symbol_type="function",
        file_path="api/v1/webhook.py",
        start_line=1,
        end_line=10,
        code_snippet="def handle_webhook():\n    if True:\n        pass\n",
        trust_zone=TrustZone.PERIMETER,
    )
    changed_files = ["api/v1/webhook.py"]

    assessment, findings = evaluate_pr_risk(
        changed_files=changed_files,
        symbols=[symbol],
        total_churn=50,
    )

    assert assessment.risk_level in [RiskLevel.HIGH, RiskLevel.CRITICAL]
    assert assessment.has_test_coverage is False
    assert assessment.perimeter_symbols_count == 1
    assert len(findings) == 1
    assert findings[0].category == FindingCategory.RISK
    assert findings[0].severity == Severity.HIGH
    assert "Untested Perimeter Modification" in findings[0].title


def test_evaluate_pr_risk_with_tests_is_low():
    symbol = ASTSymbolScope(
        symbol_name="helper",
        symbol_type="function",
        file_path="utils/helper.py",
        start_line=1,
        end_line=5,
        code_snippet="def helper(): return 1\n",
        trust_zone=TrustZone.INTERNAL_CORE,
    )
    changed_files = ["utils/helper.py", "tests/test_helper.py"]

    assessment, findings = evaluate_pr_risk(
        changed_files=changed_files,
        symbols=[symbol],
        total_churn=10,
    )

    assert assessment.risk_level == RiskLevel.LOW
    assert assessment.has_test_coverage is True
    assert len(findings) == 0
