"""
Sandbox Harness: Container-isolated test runner with strict outcome classification.
Untrusted PR code is never executed directly on the host machine.
"""

import os
import re
import shutil
import subprocess
import tempfile
from typing import Optional, Tuple

from sentinel.config import default_config
from sentinel.state import ProofStatus


def is_docker_available() -> bool:
    """Checks whether the Docker daemon is available and accessible."""
    docker_bin = shutil.which("docker")
    if not docker_bin:
        return False
    try:
        res = subprocess.run(
            [docker_bin, "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
            check=False,
        )
        return res.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def classify_pytest_output(returncode: int, output: str) -> ProofStatus:
    """
    Classifies raw pytest output into strict ProofStatus states.
    Guarantees that environment, import, syntax, and fixture failures cannot be classified as dynamic proof.
    """
    if returncode == 0:
        return ProofStatus.NOT_REPRODUCED

    # Check for collection, syntax, import, or fixture errors
    setup_error_patterns = [
        r"SyntaxError:",
        r"ImportError:",
        r"ModuleNotFoundError:",
        r"NameError:",
        r"fixture\s+.*?\s+not found",
        r"pytest:\s+error",
        r"UsageError:",
        r"INTERNALERROR",
        r"ERROR\s+collecting",
        r"failed on setup",
        r"Target function not located",
    ]
    for pattern in setup_error_patterns:
        if re.search(pattern, output, re.IGNORECASE):
            return ProofStatus.EXECUTION_FAILED

    if returncode in [2, 3, 4, 5]:
        return ProofStatus.EXECUTION_FAILED

    # Successful dynamic reproduction requires a clean test run with explicit assertion failure in the test body
    if returncode == 1:
        has_failed_test = bool(re.search(r"FAILED\s+test_repro\.py::", output))
        has_assertion = "AssertionError" in output or "assert " in output
        if has_failed_test and has_assertion:
            return ProofStatus.REPRODUCED_DYNAMICALLY

    return ProofStatus.EXECUTION_FAILED


def execute_test_script(
    script_code: str,
    timeout: int = default_config.sandbox_timeout_seconds,
    docker_image: str = "python:3.11-slim",
) -> Tuple[ProofStatus, str]:
    """
    Executes a synthesized reproduction test script strictly inside an isolated container sandbox.
    If container isolation is unavailable, refuses execution on host and returns SANDBOX_UNAVAILABLE.
    """
    if not script_code.strip():
        return ProofStatus.UNTESTED, "Empty test script provided."

    # Host execution safety check: untrusted PR code must never run on host
    if not is_docker_available():
        return (
            ProofStatus.SANDBOX_UNAVAILABLE,
            "Container isolation (Docker) is unavailable or daemon is offline. "
            "Host execution of untrusted code is blocked for security.",
        )

    with tempfile.TemporaryDirectory() as temp_dir:
        test_file_path = os.path.join(temp_dir, "test_repro.py")
        with open(test_file_path, "w", encoding="utf-8") as f:
            f.write(script_code)

        docker_bin = shutil.which("docker") or "docker"
        docker_args = [
            docker_bin,
            "run",
            "--rm",
            "--network=none",
            "--memory=512m",
            "--cpus=1.0",
            "--user=nobody",
            "-v",
            f"{temp_dir}:/sandbox:ro",
            "-w",
            "/sandbox",
            docker_image,
            "pytest",
            "test_repro.py",
            "-v",
            "--tb=short",
        ]

        try:
            result = subprocess.run(
                docker_args,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            output = f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            proof_status = classify_pytest_output(result.returncode, output)
            return proof_status, output

        except subprocess.TimeoutExpired:
            return ProofStatus.TIMEOUT, f"Execution timed out after {timeout} seconds."
        except Exception as e:
            return ProofStatus.EXECUTION_FAILED, f"Sandbox error executing test in container: {str(e)}"

