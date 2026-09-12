"""
Risk & Blast Radius Agent: Evaluates PR churn density, cyclomatic complexity,
public perimeter exposure, and missing test coverage risks.
"""

import ast
from typing import Any, Dict, List, Tuple
import uuid

from sentinel.state import (
    ASTSymbolScope,
    Finding,
    FindingCategory,
    PRReviewState,
    ProofStatus,
    RiskAssessment,
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


def evaluate_pr_risk(
    changed_files: List[str],
    symbols: List[ASTSymbolScope],
    total_churn: int,
) -> Tuple[RiskAssessment, List[Finding]]:
    """
    Evaluates PR risk level, computes blast radius, and flags untested perimeter modifications.
    """
    findings: List[Finding] = []

    # 1. Check for test file presence in the PR
    test_files = [
        f for f in changed_files
        if "test" in f.lower() or f.startswith("tests/") or f.endswith("_test.py") or f.endswith("test.py")
    ]
    has_test_coverage = len(test_files) > 0

    # 2. Total cyclomatic complexity of changed symbols
    total_complexity = sum(compute_symbol_cyclomatic_complexity(s) for s in symbols)

    # 3. Perimeter symbol exposure
    perimeter_symbols = [s for s in symbols if s.trust_zone == TrustZone.PERIMETER]
    perimeter_count = len(perimeter_symbols)

    # 4. Determine overall PR Risk Level
    if total_churn > 500 or (perimeter_count > 0 and not has_test_coverage and total_complexity > 10):
        risk_level = RiskLevel.CRITICAL
    elif (perimeter_count > 0 and not has_test_coverage) or (total_complexity > 10 and not has_test_coverage):
        risk_level = RiskLevel.HIGH
    elif total_complexity > 5 or total_churn > 150:
        risk_level = RiskLevel.MEDIUM
    else:
        risk_level = RiskLevel.LOW

    # 5. Flag Untested Public Perimeter Modifications
    if perimeter_symbols and not has_test_coverage:
        for symbol in perimeter_symbols:
            findings.append(
                Finding(
                    id=f"RISK-{uuid.uuid4().hex[:8]}",
                    category=FindingCategory.RISK,
                    severity=Severity.HIGH,
                    file_path=symbol.file_path,
                    start_line=symbol.start_line,
                    end_line=symbol.end_line,
                    title=f"Untested Perimeter Modification ({symbol.symbol_name})",
                    explanation=(
                        f"Public perimeter symbol '{symbol.symbol_name}' was modified without accompanying "
                        "test updates in this pull request. Changes to external API boundaries carry high "
                        "blast radius and require automated unit or integration tests."
                    ),
                    suggested_fix="Add unit or integration tests verifying boundary behavior and edge cases.",
                    trust_zone=symbol.trust_zone,
                    proof_status=ProofStatus.STATIC_VERIFIED,
                )
            )

    summary_text = (
        f"PR Risk: {risk_level.value} (Churn: {total_churn} lines, "
        f"Complexity Delta: {total_complexity}, "
        f"Perimeter Exposed: {perimeter_count}, "
        f"Tests Included: {'Yes' if has_test_coverage else 'No'})"
    )

    assessment = RiskAssessment(
        risk_level=risk_level,
        cyclomatic_complexity=total_complexity,
        total_churn_lines=total_churn,
        perimeter_symbols_count=perimeter_count,
        has_test_coverage=has_test_coverage,
        summary=summary_text,
    )

    return assessment, findings


def risk_agent_node(state: PRReviewState) -> Dict[str, Any]:
    """
    LangGraph node: Analyzes PR blast radius, complexity delta, and missing test coverage.
    Returns candidate findings and RiskAssessment.
    """
    changed_files = state.get("changed_files", [])
    symbols = state.get("symbols", [])
    hunks = state.get("hunks", [])

    total_churn = sum(hunk.new_lines for hunk in hunks)

    assessment, findings = evaluate_pr_risk(
        changed_files=changed_files,
        symbols=symbols,
        total_churn=total_churn,
    )

    return {
        "candidate_findings": findings,
        "risk_assessment": assessment,
    }
