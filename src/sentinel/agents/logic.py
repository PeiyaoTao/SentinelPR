"""
Logic Agent: Identifies logic flaws, concurrency hazards, mutable defaults, and unhandled edge cases.
"""

import ast
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


def _scope_nodes(node: ast.AST):
    """Walk a lexical body without mixing declarations from nested scopes."""
    yield node
    for child in ast.iter_child_nodes(node):
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            yield from _scope_nodes(child)


def global_mutations(tree: ast.AST) -> list[tuple[ast.AugAssign, str]]:
    mutations = []
    for scope in ast.walk(tree):
        if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        nodes = list(_scope_nodes(scope))
        names = {name for node in nodes if isinstance(node, ast.Global) for name in node.names}
        for node in nodes:
            if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and node.target.id in names:
                mutations.append((node, node.target.id))
    return mutations


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

    # A syntactic global mutation is a hypothesis, not proof of concurrent access.
    for node, name in global_mutations(tree):
        line = symbol.start_line + node.lineno - 1
        findings.append(Finding(
            id=f"LOGIC-{uuid.uuid4().hex[:8]}", rule_id="logic.global-mutation",
            category=FindingCategory.LOGIC, severity=Severity.HIGH,
            file_path=symbol.file_path, start_line=line, end_line=line,
            title="Global mutation needs concurrency context",
            explanation=f"Augmented assignment mutates declared global '{name}'. Concurrent access and synchronization have not been established; this is a hypothesis, not a demonstrated race.",
            suggested_fix="Inspect callers and synchronization before changing the code. If concurrent unsynchronized access is possible, protect the shared operation or remove shared mutable state.",
            trust_zone=symbol.trust_zone, proof_status=ProofStatus.UNTESTED,
            hypothesis=True,
        ))

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
