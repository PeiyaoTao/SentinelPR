from unittest.mock import patch
from sentinel.harness.sandbox import classify_pytest_output, execute_test_script, is_docker_available
from sentinel.state import ProofStatus


def test_docker_unavailable_refuses_host_execution():
    with patch("sentinel.harness.sandbox.is_docker_available", return_value=False):
        status, log = execute_test_script('import os; os.system("echo compromised")')
        assert status == ProofStatus.SANDBOX_UNAVAILABLE
        assert "Host execution of untrusted code is blocked" in log


def test_classify_pytest_output_states():
    # 1. Clean test pass (not reproduced)
    assert classify_pytest_output(0, "1 passed in 0.05s") == ProofStatus.NOT_REPRODUCED

    # 2. Syntax / Import / Fixture error (execution failed, NOT reproduced)
    syntax_err = "SyntaxError: invalid syntax"
    assert classify_pytest_output(1, syntax_err) == ProofStatus.EXECUTION_FAILED

    import_err = "ModuleNotFoundError: No module named foo"
    assert classify_pytest_output(2, import_err) == ProofStatus.EXECUTION_FAILED

    fixture_err = "fixture user_client not found"
    assert classify_pytest_output(1, fixture_err) == ProofStatus.EXECUTION_FAILED

    # 3. Valid dynamic assertion failure
    valid_repro = """
    FAILED test_repro.py::test_reproduce - AssertionError: assert ['item'] == []
    1 failed in 0.10s
    """
    assert classify_pytest_output(1, valid_repro) == ProofStatus.REPRODUCED_DYNAMICALLY

    # 4. Target function not located
    unlocated = "Target function not located"
    assert classify_pytest_output(1, unlocated) == ProofStatus.EXECUTION_FAILED
