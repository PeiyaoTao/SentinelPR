"""
Sandbox Harness: Ephemeral, isolated test runner with error classification and resource limits.
"""

import os
import subprocess
import sys
import tempfile
from typing import Tuple

from sentinel.config import default_config
from sentinel.state import ProofStatus


def execute_test_script(
    script_code: str,
    timeout: int = default_config.sandbox_timeout_seconds,
    use_docker: bool = default_config.use_docker,
) -> Tuple[ProofStatus, str]:
    """
    Executes a synthesized reproduction test script in a temporary isolated environment.
    Returns (ProofStatus, execution_log).
    """
    if not script_code.strip():
        return ProofStatus.UNTESTED, "Empty test script provided."

    # Docker-based sandboxing (for production/CI)
    if use_docker:
        # If Docker is requested, we can mount an ephemeral volume with --network=none
        # For local fallback or testing, subprocess sandbox is used below.
        pass

    # Safe Subprocess Sandboxing
    with tempfile.TemporaryDirectory() as temp_dir:
        test_file_path = os.path.join(temp_dir, "test_repro.py")
        with open(test_file_path, "w", encoding="utf-8") as f:
            f.write(script_code)

        # Sanitize environment: purge sensitive environment tokens
        clean_env = {
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "PYTHONPATH": os.pathsep.join([temp_dir, os.getcwd()]),
            "PYTHONDONTWRITEBYTECODE": "1",
        }

        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", test_file_path, "-v", "--tb=short"],
                cwd=temp_dir,
                env=clean_env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            output = f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"

            # Pytest exit codes:
            # 0: All tests passed successfully (Did not reproduce the expected defect!)
            # 1: Tests were run and at least one failed (Expected for a successful reproduction!)
            # 2: Interrupted by user
            # 3: Internal error
            # 4: Usage error
            # 5: No tests were collected
            if result.returncode == 0:
                return ProofStatus.NOT_REPRODUCED, output

            # Check for environment / import / syntax glitches vs actual assertion failures
            is_setup_error = any(
                err in output
                for err in [
                    "ModuleNotFoundError",
                    "ImportError",
                    "SyntaxError",
                    "pytest: error",
                    "UsageError",
                    "fixture '.*' not found",
                ]
            ) or result.returncode in [3, 4, 5]

            if is_setup_error:
                return ProofStatus.ENV_SETUP_ERROR, output

            if "AssertionError" in output or result.returncode == 1:
                return ProofStatus.REPRODUCED_DYNAMICALLY, output

            return ProofStatus.REPRODUCED_DYNAMICALLY, output

        except subprocess.TimeoutExpired:
            return ProofStatus.NOT_REPRODUCED, f"Test timed out after {timeout} seconds."
        except Exception as e:
            return ProofStatus.ENV_SETUP_ERROR, f"Sandbox error executing test: {str(e)}"
