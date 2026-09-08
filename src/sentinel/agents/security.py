"""
Security Agent: Taint tracking, boundary threat modeling, and injection/secret vulnerability detection.
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
    TrustZone,
)


SECRET_PATTERNS = [
    (re.compile(r"""(?i)(?:password|secret|api_key|access_token|private_key)\s*=\s*['"][a-zA-Z0-9_\-]{16,}['"]"""), "Hardcoded Credential/Secret"),
    (re.compile(r"""AKIA[0-9A-Z]{16}"""), "Hardcoded AWS Access Key"),
]


def analyze_symbol_security(symbol: ASTSymbolScope) -> List[Finding]:
    """
    Performs security taint and boundary threat analysis on a symbol scope.
    """
    findings: List[Finding] = []
    code = symbol.code_snippet

    # Check 1: Hardcoded Secrets
    for pattern, title in SECRET_PATTERNS:
        match = pattern.search(code)
        if match:
            # Estimate line number from offset
            line_offset = code[: match.start()].count("\n")
            lineno = symbol.start_line + line_offset
            findings.append(
                Finding(
                    id=f"SEC-{uuid.uuid4().hex[:8]}",
                    category=FindingCategory.SECURITY,
                    severity=Severity.CRITICAL,
                    file_path=symbol.file_path,
                    start_line=lineno,
                    end_line=lineno,
                    title=title,
                    explanation="Potential plaintext credential or API secret exposed directly in source code.",
                    suggested_fix="Inject secrets via secure environment variables or a secrets manager (e.g. AWS Secrets Manager, Vault).",
                    trust_zone=symbol.trust_zone,
                    proof_status=ProofStatus.STATIC_VERIFIED,
                )
            )

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return findings

    # AST-based security checks
    for node in ast.walk(tree):
        # Check 2: Dangerous shell=True in subprocess
        if isinstance(node, ast.Call):
            func_name = ""
            if isinstance(node.func, ast.Attribute):
                func_name = node.func.attr
            elif isinstance(node.func, ast.Name):
                func_name = node.func.id

            if func_name in ["run", "Popen", "call", "check_output", "system"]:
                for kw in node.keywords:
                    if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                        lineno = symbol.start_line + (node.lineno - 1)
                        findings.append(
                            Finding(
                                id=f"SEC-{uuid.uuid4().hex[:8]}",
                                category=FindingCategory.SECURITY,
                                severity=Severity.CRITICAL,
                                file_path=symbol.file_path,
                                start_line=lineno,
                                end_line=lineno,
                                title="Command Injection Vector (shell=True)",
                                explanation="Invoking subprocess with shell=True executes commands through the system shell, enabling arbitrary shell injection if parameters contain untrusted input.",
                                suggested_fix="Pass arguments as a list without shell=True, or sanitize with shlex.quote.",
                                trust_zone=symbol.trust_zone,
                                proof_status=ProofStatus.STATIC_VERIFIED,
                            )
                        )

            # Check 3: Raw SQL formatted strings in cursor.execute
            if func_name == "execute" and node.args:
                first_arg = node.args[0]
                if isinstance(first_arg, ast.JoinedStr) or (
                    isinstance(first_arg, ast.BinOp) and isinstance(first_arg.op, (ast.Mod, ast.Add))
                ):
                    lineno = symbol.start_line + (node.lineno - 1)
                    findings.append(
                        Finding(
                            id=f"SEC-{uuid.uuid4().hex[:8]}",
                            category=FindingCategory.SECURITY,
                            severity=Severity.CRITICAL,
                            file_path=symbol.file_path,
                            start_line=lineno,
                            end_line=lineno,
                            title="SQL Injection via String Formatting",
                            explanation="SQL query is assembled using dynamic string interpolation/concatenation rather than parameterized placeholders.",
                            suggested_fix="Use parameterized queries (e.g. cursor.execute('SELECT * FROM users WHERE id = %s', (user_id,))) to prevent SQL injection.",
                            trust_zone=symbol.trust_zone,
                            proof_status=ProofStatus.STATIC_VERIFIED,
                        )
                    )

            # Check 4: Insecure eval / exec
            if func_name in ["eval", "exec"]:
                lineno = symbol.start_line + (node.lineno - 1)
                findings.append(
                    Finding(
                        id=f"SEC-{uuid.uuid4().hex[:8]}",
                        category=FindingCategory.SECURITY,
                        severity=Severity.HIGH,
                        file_path=symbol.file_path,
                        start_line=lineno,
                        end_line=lineno,
                        title=f"Arbitrary Code Execution Risk ({func_name})",
                        explanation=f"Direct call to '{func_name}' dynamically compiles and executes code, allowing untrusted payload execution.",
                        suggested_fix="Avoid dynamic evaluation; use ast.literal_eval for safe literal parsing or refactor to typed dispatch.",
                        trust_zone=symbol.trust_zone,
                        proof_status=ProofStatus.STATIC_VERIFIED,
                    )
                )

    return findings


def security_agent_node(state: PRReviewState) -> Dict[str, Any]:
    """
    LangGraph node: Ingests AST symbols and flags boundary vulnerabilities.
    Returns candidate findings for parallel accumulation.
    """
    symbols = state.get("symbols", [])
    candidate_findings: List[Finding] = []

    for symbol in symbols:
        findings = analyze_symbol_security(symbol)
        candidate_findings.extend(findings)

    return {"candidate_findings": candidate_findings}
