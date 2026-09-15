"""
Tests for Risk & Blast Radius Agent.
"""

from sentinel.agents.risk import compute_churn, compute_symbol_cyclomatic_complexity, evaluate_pr_risk, is_test_file
from sentinel.state import ASTSymbolScope, DiffHunk, RiskLevel, Severity, TrustZone


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
    assert complexity >= 5


def test_is_test_file_strict_matching():
    # Should match valid test files
    assert is_test_file("tests/test_api.py") is True
    assert is_test_file("src/tests/helper.py") is True
    assert is_test_file("tests/unit/test_auth.py") is True
    assert is_test_file("service_test.py") is True

    # Must NOT match non-test files with substring 'test'
    assert is_test_file("contest_utils.py") is False
    assert is_test_file("attestation.py") is False
    assert is_test_file("domain/protest.py") is False


def test_compute_churn_excludes_context():
    hunk = DiffHunk(
        file_path="app.py",
        old_start=1,
        old_lines=5,
        new_start=1,
        new_lines=5,
        content="@@ -1,5 +1,5 @@\n context line 1\n-removed line\n+added line 1\n+added line 2\n context line 2",
    )
    # Hunk has 5 lines total, but only 1 removal and 2 additions = 3 churn
    assert compute_churn([hunk]) == 3


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

    assessment, risk_indicators = evaluate_pr_risk(
        changed_files=changed_files,
        symbols=[symbol],
        total_churn=50,
    )

    assert assessment.risk_level in [RiskLevel.HIGH, RiskLevel.CRITICAL]
    assert assessment.has_test_coverage is False
    assert assessment.perimeter_symbols_count == 1
    assert len(risk_indicators) == 1
    assert risk_indicators[0].name == "Untested Perimeter Modification"
    assert risk_indicators[0].severity == Severity.HIGH


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

    assessment, risk_indicators = evaluate_pr_risk(
        changed_files=changed_files,
        symbols=[symbol],
        total_churn=10,
    )

    assert assessment.risk_level == RiskLevel.LOW
    assert assessment.has_test_coverage is True
    assert len(risk_indicators) == 0
