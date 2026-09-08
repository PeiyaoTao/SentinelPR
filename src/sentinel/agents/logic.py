"""
Logic Agent: Identifies logic flaws, concurrency hazards, mutable defaults, and unhandled edge cases.
"""

import ast
import re
from typing import Any, Dict, List
import uuid

from sentinel.state import (
    ASTSymbolScope,
    Finding,
    FindingCategory,
    PRReviewState,
    ProofStatus,
    Severity,
)


def analyze_symbol_logic(symbol: ASTSymbolScope) -> List[Finding]:
    """
    Performs deterministic AST and heuristic analysis on a symbol scope for logic defects.
    Can be augmented by LLM prompts for deep reasoning.
    """
    findings: List[Finding] = []
    code = symbol.code_snippet

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return findings

    # Check 1: Dangerous mutable default arguments (def func(items=[]))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for default in node.args.defaults + node.args.kw_defaults:
                if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                    lineno = symbol.start_line + (default.lineno - 1)
                    findings.append(
                        Finding(
                            id=f"LOGIC-{uuid.uuid4().hex[:8]}",
                            category=FindingCategory.LOGIC,
                            severity=Severity.HIGH,
                            file_path=symbol.file_path,
                            start_line=lineno,
                            end_line=lineno,
                            title="Dangerous Mutable Default Argument",
                            explanation=(
                                f"Function '{node.name}' uses a mutable default argument ({ast.dump(default)}). "
                                "Python default arguments are evaluated once at function definition time, causing "
                                "state mutation to persist across multiple function calls."
                            ),
                            suggested_fix="Use 'None' as the default argument and initialize the mutable container inside the function body.",
                            trust_zone=symbol.trust_zone,
                            proof_status=ProofStatus.UNTESTED,
                        )
                    )

    # Check 2: Potential infinite loops (while True without break/return/raise)
    for node in ast.walk(tree):
        if isinstance(node, ast.While):
            # Check if condition is a truthy constant
            is_constant_true = (
                isinstance(node.test, ast.Constant) and bool(node.test.value) is True
            )
            if is_constant_true:
                has_exit = any(
                    isinstance(child, (ast.Break, ast.Return, ast.Raise))
                    for child in ast.walk(node)
                )
                if not has_exit:
                    lineno = symbol.start_line + (node.lineno - 1)
                    findings.append(
                        Finding(
                            id=f"LOGIC-{uuid.uuid4().hex[:8]}",
                            category=FindingCategory.LOGIC,
                            severity=Severity.CRITICAL,
                            file_path=symbol.file_path,
                            start_line=lineno,
                            end_line=lineno,
                            title="Unbounded Infinite Loop",
                            explanation="While loop condition is statically true with no break, return, or raise statements in its body.",
                            suggested_fix="Ensure a loop termination condition or explicit break/raise is present.",
                            trust_zone=symbol.trust_zone,
                            proof_status=ProofStatus.UNTESTED,
                        )
                    )

    # Check 3: Concurrency / Shared State non-atomic mutation heuristic
    if re.search(r"global\s+\w+", code) and ("+=" in code or "-=" in code):
        findings.append(
            Finding(
                id=f"LOGIC-{uuid.uuid4().hex[:8]}",
                category=FindingCategory.LOGIC,
                severity=Severity.HIGH,
                file_path=symbol.file_path,
                start_line=symbol.start_line,
                end_line=symbol.end_line,
                title="Potential Thread-Safety Hazard on Global State",
                explanation=(
                    f"Symbol '{symbol.symbol_name}' modifies global state using in-place operations. "
                    "In multi-threaded environments, this causes race conditions due to non-atomic byte code execution."
                ),
                suggested_fix="Protect shared state access with threading.Lock or encapsulate within a thread-safe context.",
                trust_zone=symbol.trust_zone,
                proof_status=ProofStatus.UNTESTED,
            )
        )

    return findings


def logic_agent_node(state: PRReviewState) -> Dict[str, Any]:
    """
    LangGraph node: Analyzes AST symbols for logic defects and concurrency hazards.
    Returns candidate findings for parallel accumulation.
    """
    symbols = state.get("symbols", [])
    candidate_findings: List[Finding] = []

    for symbol in symbols:
        findings = analyze_symbol_logic(symbol)
        candidate_findings.extend(findings)

    return {"candidate_findings": candidate_findings}
