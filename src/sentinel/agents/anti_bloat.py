"""
Anti-Bloat Auditor: Identifies overprotective defensive code, ghost null-checks,
and silent error swallowing while strictly respecting the Trust Boundary Matrix.
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
    TrustZone,
)


def analyze_symbol_anti_bloat(symbol: ASTSymbolScope) -> List[Finding]:
    """
    Audits symbol for defensive bloat and anti-patterns violating Fail-Fast.
    Strictly skips perimeter code where defensive checks are required.
    """
    findings: List[Finding] = []

    # Rule 1: PERIMETER code is exempt from anti-bloat validation flagging
    if symbol.trust_zone == TrustZone.PERIMETER:
        # At perimeter (controllers, API endpoints), defensive checks are mandatory.
        # Only flag truly egregious antipatterns like bare except pass at the perimeter.
        pass

    try:
        tree = ast.parse(symbol.code_snippet)
    except SyntaxError:
        return findings

    # Check 1: Pokemon exception handling (except Exception: pass / bare except: pass)
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for handler in node.handlers:
                # Bare except or except Exception / BaseException
                is_broad = False
                if handler.type is None:
                    is_broad = True
                elif isinstance(handler.type, ast.Name) and handler.type.id in ["Exception", "BaseException"]:
                    is_broad = True

                # Check if body is just 'pass' or empty
                is_swallowing = len(handler.body) == 1 and isinstance(handler.body[0], ast.Pass)

                if is_broad and is_swallowing:
                    lineno = symbol.start_line + (handler.lineno - 1)
                    findings.append(
                        Finding(
                            id=f"BLOAT-{uuid.uuid4().hex[:8]}",
                            category=FindingCategory.ANTI_BLOAT,
                            severity=Severity.HIGH,
                            file_path=symbol.file_path,
                            start_line=lineno,
                            end_line=lineno,
                            title="Silent Error Swallowing (Pokemon Exception)",
                            explanation=(
                                "Catching broad 'Exception' and silently swallowing it with 'pass' directly violates "
                                "the Fail-Fast Principle. It conceals syntax errors, missing attributes, and fatal "
                                "subsystem failures."
                            ),
                            suggested_fix="Catch the specific expected exception type and log it, or allow it to propagate.",
                            trust_zone=symbol.trust_zone,
                            proof_status=ProofStatus.STATIC_VERIFIED,
                        )
                    )

    # Check 2: Ghost Null-Checks & Paranoid defensive if-statements in INTERNAL_CORE
    if symbol.trust_zone == TrustZone.INTERNAL_CORE:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Inspect type annotations on parameters
                typed_args = {}
                for arg in node.args.args:
                    if arg.annotation and isinstance(arg.annotation, ast.Name):
                        typed_args[arg.arg] = arg.annotation.id

                # Scan function body for top-level ghost checks: if param is None: return None
                for stmt in node.body:
                    if isinstance(stmt, ast.If):
                        # Detect pattern: if arg is None or not arg
                        is_ghost_check = False
                        checked_var = None

                        if isinstance(stmt.test, ast.Compare):
                            if isinstance(stmt.test.left, ast.Name) and stmt.test.left.id in typed_args:
                                for op, comp in zip(stmt.test.ops, stmt.test.comparators):
                                    if isinstance(op, (ast.Is, ast.Eq)) and isinstance(comp, ast.Constant) and comp.value is None:
                                        is_ghost_check = True
                                        checked_var = stmt.test.left.id

                        # Check if the handler just returns None/empty/sentinel
                        returns_sentinel = False
                        if len(stmt.body) == 1 and isinstance(stmt.body[0], ast.Return):
                            ret_val = stmt.body[0].value
                            if ret_val is None:
                                returns_sentinel = True
                            elif isinstance(ret_val, ast.Constant) and (
                                ret_val.value is None or ret_val.value in [0, 0.0, False, "", b""]
                            ):
                                returns_sentinel = True
                            elif isinstance(ret_val, (ast.List, ast.Dict, ast.Set)):
                                elements = ret_val.elts if hasattr(ret_val, "elts") else ret_val.keys
                                if len(elements) == 0:
                                    returns_sentinel = True

                        if is_ghost_check and returns_sentinel and checked_var:
                            lineno = symbol.start_line + (stmt.lineno - 1)
                            findings.append(
                                Finding(
                                    id=f"BLOAT-{uuid.uuid4().hex[:8]}",
                                    category=FindingCategory.ANTI_BLOAT,
                                    severity=Severity.SUGGESTION,
                                    file_path=symbol.file_path,
                                    start_line=lineno,
                                    end_line=lineno,
                                    title=f"Ghost Null-Check on Internal Parameter '{checked_var}'",
                                    explanation=(
                                        f"Parameter '{checked_var}: {typed_args.get(checked_var)}' is annotated with a "
                                        "non-optional type in an internal domain core method. Checking 'if ... is None' and "
                                        "returning None masks upstream contract violations rather than failing fast."
                                    ),
                                    suggested_fix="Rely on the type contract and upstream caller guarantees, or raise a ValueError/AssertionError if precondition is violated.",
                                    trust_zone=symbol.trust_zone,
                                    proof_status=ProofStatus.STATIC_VERIFIED,
                                )
                            )

    return findings


def anti_bloat_agent_node(state: PRReviewState) -> Dict[str, Any]:
    """
    LangGraph node: Audits AST symbols for defensive bloat and fail-fast violations.
    Returns candidate findings for parallel accumulation.
    """
    symbols = state.get("symbols", [])
    candidate_findings: List[Finding] = []

    for symbol in symbols:
        findings = analyze_symbol_anti_bloat(symbol)
        candidate_findings.extend(findings)

    return {"candidate_findings": candidate_findings}
