"""
Risk & Blast Radius Agent: Evaluates PR churn density, cyclomatic complexity,
public perimeter exposure, and missing test coverage risks.
"""

import ast
from typing import Any, Dict, List, Optional, Tuple
import uuid

from sentinel.state import (
    ASTSymbolScope,
    Finding,
    FindingCategory,
    PRReviewState,
    ProofStatus,
    RiskAssessment,
    RiskIndicator,
    RiskLevel,
    Severity,
    TrustZone,
)


def compute_symbol_cyclomatic_complexity(symbol: ASTSymbolScope) -> int:
    """
    Calculates cyclomatic complexity for a symbol scope by counting
    decision points and branch control flow nodes.
    """
    try:
        tree = ast.parse(symbol.code_snippet)
    except SyntaxError:
        return 1

    complexity = 1
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.While, ast.For, ast.AsyncFor)):
            complexity += 1
        elif isinstance(node, ast.ExceptHandler):
            complexity += 1
        elif isinstance(node, ast.BoolOp):
            # Each 'and' / 'or' adds a decision branch
            complexity += len(node.values) - 1

    return complexity


def is_test_file(path: str) -> bool:
    """Identifies whether a file path belongs to a test suite."""
    norm = path.replace("\\", "/").lower()
    parts = norm.split("/")
    filename = parts[-1]
    in_test_dir = any(p in ["tests", "test", "__tests__"] for p in parts[:-1])
    is_test_filename = filename.startswith("test_") or filename.endswith("_test.py") or filename == "test.py"
    return in_test_dir or is_test_filename


def compute_churn(hunks: List[Any]) -> int:
    """Calculates total line additions and deletions across all hunks (excluding context)."""
    churn = 0
    for hunk in hunks:
        for line in hunk.content.splitlines():
            if line.startswith("@@"):
                continue
            elif line.startswith("+") or line.startswith("-"):
                churn += 1
    return churn


def evaluate_pr_risk(
    changed_files: List[str],
    symbols: List[ASTSymbolScope],
    total_churn: int,
    base_files: Optional[Dict[str, str]] = None,
) -> Tuple[RiskAssessment, List[RiskIndicator]]:
    """
    Evaluates PR risk level, computes blast radius, and produces advisory risk indicators.
    Does NOT emit blocking defects.
    """
    risk_indicators: List[RiskIndicator] = []

    # 1. Check for test file presence in the PR using strict pattern matching
    has_test_coverage = any(is_test_file(f) for f in changed_files)

    # 2. Total cyclomatic complexity of changed symbols
    total_complexity = sum(compute_symbol_cyclomatic_complexity(s) for s in symbols)

    # 3. Perimeter symbol exposure
    perimeter_symbols = [s for s in symbols if s.trust_zone == TrustZone.PERIMETER]
    perimeter_count = len(perimeter_symbols)

    # 4. Determine overall PR Review effort
    if total_churn > 500 or (perimeter_count > 0 and not has_test_coverage) or (total_complexity > 10 and not has_test_coverage):
        risk_level = RiskLevel.HIGH
    elif total_complexity > 5 or total_churn > 150:
        risk_level = RiskLevel.MEDIUM
    else:
        risk_level = RiskLevel.LOW

    # 5. Advisory Risk Indicator for Untested Public Perimeter Modifications
    if perimeter_symbols and not has_test_coverage:
        sym_names = ", ".join(s.symbol_name for s in perimeter_symbols[:3])
        risk_indicators.append(
            RiskIndicator(
                name="Untested Perimeter Modification",
                severity=Severity.HIGH,
                metric_value=f"{perimeter_count} public symbol(s)",
                description=(
                    f"Public perimeter symbol(s) ({sym_names}) were modified without accompanying "
                    "test updates in this pull request. Public entrypoints have high blast radius."
                ),
            )
        )

    summary_text = (
        f"PR review effort: {risk_level.value} (Churn: {total_churn} lines, "
        f"Changed-scope complexity sum: {total_complexity}, "
        f"Perimeter Exposed: {perimeter_count}, "
        f"Test files changed: {'Yes' if has_test_coverage else 'No'})"
    )

    assessment = RiskAssessment(
        risk_level=risk_level,
        cyclomatic_complexity=total_complexity,
        total_churn_lines=total_churn,
        perimeter_symbols_count=perimeter_count,
        has_test_coverage=has_test_coverage,
        summary=summary_text,
    )

    return assessment, risk_indicators


def risk_agent_node(state: PRReviewState) -> Dict[str, Any]:
    """
    LangGraph node: Analyzes PR blast radius, complexity delta, and missing test coverage.
    Returns advisory risk indicators and RiskAssessment without creating blocking findings.
    """
    changed_files = state.get("changed_files", [])
    symbols = state.get("symbols", [])
    hunks = state.get("hunks", [])
    base_files = state.get("base_files", {})

    total_churn = compute_churn(hunks)

    assessment, risk_indicators = evaluate_pr_risk(
        changed_files=changed_files,
        symbols=symbols,
        total_churn=total_churn,
        base_files=base_files,
    )

    return {
        "candidate_findings": [],
        "risk_assessment": assessment,
        "risk_indicators": risk_indicators,
    }
