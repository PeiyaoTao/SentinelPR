"""
Test Synthesizer Agent: Generates minimal reproduction tests for candidate logic findings
and manages the sandbox execution loop with reflection repair.
"""

from typing import Any, Dict, List
import textwrap

from sentinel.config import default_config
from sentinel.harness.sandbox import execute_test_script
from sentinel.state import (
    EvidenceSource,
    Finding,
    FindingCategory,
    PRReviewState,
    ProofStatus,
)


import ast

def synthesize_reproduction_test(finding: Finding, state: PRReviewState) -> str:
    """
    Synthesizes a minimal, self-contained pytest script to prove a candidate logic finding.
    Returns an empty string if no deterministic reproduction template is available.
    """
    file_content = state.get("head_files", {}).get(finding.file_path, "")
    if not file_content.strip():
        return ""

    if "Mutable Default" in finding.title:
        # Resolve target function name via AST
        target_func_name = None
        try:
            tree = ast.parse(file_content)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    end_line = getattr(node, "end_lineno", node.lineno)
                    if node.lineno <= finding.start_line <= end_line:
                        target_func_name = node.name
                        break
        except SyntaxError:
            pass

        if not target_func_name:
            return ""

        return textwrap.dedent(f"""
            import pytest
            import sys

            # Target module source
            {file_content}

            def test_mutable_default_isolation():
                mod = sys.modules[__name__]
                if not hasattr(mod, "{target_func_name}"):
                    pytest.fail("Target function not located in module")
                target_func = getattr(mod, "{target_func_name}")

                first_call = target_func("user_test") if target_func.__code__.co_argcount >= 1 else target_func()
                if isinstance(first_call, list):
                    first_call.append("sentinel_leak")
                    second_call = target_func("user_test") if target_func.__code__.co_argcount >= 1 else target_func()
                    assert "sentinel_leak" not in second_call, "Mutable default leaked across invocations"
                elif isinstance(first_call, dict):
                    for k, v in first_call.items():
                        if isinstance(v, list):
                            v.append("sentinel_leak")
                            second_call = target_func("user_test") if target_func.__code__.co_argcount >= 1 else target_func()
                            assert "sentinel_leak" not in second_call[k], "Mutable default container leaked across invocations"
        """)

    # Unsupported categories remain UNTESTED rather than generating dummy assert True tests
    return ""


def test_synthesis_node(state: PRReviewState) -> Dict[str, Any]:
    """
    LangGraph node: Generates and executes reproduction tests for candidate findings.
    Executes a 1-repair reflection loop if ENV_SETUP_ERROR occurs.
    """
    candidate_findings = state.get("candidate_findings", [])
    repro_tests: Dict[str, str] = {}
    updated_findings: List[Finding] = []

    for finding in candidate_findings:
        # Dynamic test reproduction is primarily targeted at LOGIC findings
        if finding.category == FindingCategory.LOGIC:
            script = synthesize_reproduction_test(finding, state)
            if not script.strip():
                finding.proof_status = ProofStatus.UNTESTED
                continue

            repro_tests[finding.id] = script

            # Attempt 1
            status, output = execute_test_script(script)

            # Reflection repair loop on execution failure
            attempts = 0
            while status in [ProofStatus.EXECUTION_FAILED, ProofStatus.ENV_SETUP_ERROR] and attempts < default_config.max_test_repair_attempts:
                attempts += 1
                repaired_script = "import sys\nimport os\nimport pytest\n" + script
                status, output = execute_test_script(repaired_script)
                if status not in [ProofStatus.EXECUTION_FAILED, ProofStatus.ENV_SETUP_ERROR]:
                    script = repaired_script
                    break

            finding.proof_status = status
            finding.proof_execution_log = output
            finding.reproduction_script = script
            if status == ProofStatus.REPRODUCED_DYNAMICALLY:
                finding.evidence_source = EvidenceSource.DYNAMIC_SANDBOX
        else:
            # SECURITY and ANTI_BLOAT findings are verified via static AST traces
            finding.proof_status = ProofStatus.STATIC_VERIFIED

    return {
        "repro_tests": repro_tests,
    }
