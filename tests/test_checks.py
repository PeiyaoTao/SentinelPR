"""Validation failures must never become clean reviews or leak raw secrets."""
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
from sentinel.checks.models import CheckResult, ValidationReport
from sentinel.checks.report import attach_validation
from sentinel.checks.runner import audit_dependencies, container_check, run_checks, scan_secrets, snapshot
from sentinel.state import ConsolidatedReport, ReviewOutcome


@pytest.mark.parametrize("status,outcome", [("passed", ReviewOutcome.CLEAN), ("failed", ReviewOutcome.CHANGES_REQUIRED), ("incomplete", ReviewOutcome.INCOMPLETE_REVIEW), ("error", ReviewOutcome.INFRASTRUCTURE_FAILURE)])
def test_checks_control_report_and_sarif(status, outcome):
    report = ConsolidatedReport(summary_markdown="Status: CLEAN")
    attach_validation(report, ValidationReport(snapshot_id="abc", results=[CheckResult(name="tests", status=status, summary="test status")]))
    assert report.review_outcome == outcome
    assert outcome.value in report.summary_markdown
    assert report.sarif_json["runs"][-1]["invocations"][0]["executionSuccessful"] == (status in ("passed", "failed"))


def test_passed_checks_do_not_erase_incomplete_analysis():
    report = ConsolidatedReport(summary_markdown="incomplete", review_outcome=ReviewOutcome.INCOMPLETE_REVIEW)
    attach_validation(report, ValidationReport(snapshot_id="a", results=[CheckResult(name="lint", status="passed", summary="clean")]))
    assert report.review_outcome == ReviewOutcome.INCOMPLETE_REVIEW


def test_secret_value_never_exported(tmp_path):
    secret = "ghp_" + "A" * 36
    (tmp_path / ".env").write_text("TOKEN=" + secret)
    result = scan_secrets(tmp_path)
    assert result.status == "failed"
    assert result.issues[0].path == ".env"
    assert secret not in result.model_dump_json()


def test_tracked_ignored_secret_is_scanned(tmp_path):
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)
    git("init")
    (tmp_path / ".gitignore").write_text(".env\n")
    (tmp_path / ".env").write_text("TOKEN=" + "ghp_" + "A" * 36)
    git("add", "-f", ".env")
    report = run_checks(tmp_path, ["secrets"])
    assert report.results[0].status == "failed"
    assert report.results[0].issues[0].path == ".env"


def test_snapshot_budget_is_incomplete(tmp_path, monkeypatch):
    (tmp_path / "large.txt").write_text("long content")
    monkeypatch.setattr("sentinel.checks.runner.MAX_FILE", 1)
    assert run_checks(tmp_path, ["secrets"]).results[0].status == "incomplete"


def test_no_host_fallback_when_docker_missing(tmp_path, monkeypatch):
    def unavailable(*args, **kwargs):
        raise FileNotFoundError("docker")
    monkeypatch.setattr("sentinel.checks.runner.subprocess.run", unavailable)
    result = container_check("tests", tmp_path, "prepared:local", 2)
    assert result.status == "incomplete"


@pytest.mark.parametrize("check,code,status", [("lint", 0, "passed"), ("types", 1, "failed"), ("tests", 1, "failed"), ("tests", 5, "incomplete"), ("tests", 2, "incomplete"), ("build", 1, "failed"), ("lint", 2, "error"), ("build", 125, "incomplete"), ("types", 124, "incomplete"), ("tests", 78, "incomplete")])
def test_container_status_and_isolation(tmp_path, monkeypatch, check, code, status):
    def execute(command, **kwargs):
        assert "--network=none" in command
        assert "--mount" not in command
        assert kwargs["stdin"].read(1)
        assert "--read-only" in command
        assert "--cap-drop=ALL" in command
        assert "--pull=never" in command
        assert "--user=65534:65534" in command
        assert "--entrypoint=python" in command
        kwargs["stdout"].write(b"sensitive tool output")
        return SimpleNamespace(returncode=code)
    monkeypatch.setattr("sentinel.checks.runner.subprocess.run", execute)
    result = container_check(check, tmp_path, "prepared:local", 5)
    assert result.status == status
    assert "sensitive" not in result.model_dump_json()


def test_timeout_removes_container(tmp_path, monkeypatch):
    calls = []
    def execute(command, **kwargs):
        calls.append(command)
        if command[1] == "run":
            raise subprocess.TimeoutExpired(command, 1)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr("sentinel.checks.runner.subprocess.run", execute)
    assert container_check("tests", tmp_path, "prepared:local", 1).status == "incomplete"
    assert calls[1][:3] == ["docker", "rm", "-f"]
    assert calls[0][calls[0].index("--name") + 1] == calls[1][-1]


@pytest.mark.parametrize("requirements", ["-e .", "thing>=1", "thing @ https://example.invalid/code.whl", "-r nested.txt", "thing==1; python_version>'3'"])
def test_audit_rejects_executable_or_unresolved_input(tmp_path, requirements):
    (tmp_path / "requirements-audit.txt").write_text(requirements)
    result = audit_dependencies(tmp_path, "requirements-audit.txt", 5)
    assert result.status == "incomplete"


def test_audit_runs_only_sanitized_pins(tmp_path, monkeypatch):
    (tmp_path / "requirements-audit.txt").write_text("demo==1.0 # comment\n")
    def execute(command, **kwargs):
        assert "--disable-pip" in command and "--no-deps" in command
        assert Path(kwargs["cwd"]) != tmp_path
        assert Path(command[-1]).read_text() == "demo==1.0\n"
        return SimpleNamespace(returncode=1, stderr=b"", stdout=json.dumps({"dependencies": [{"name": "demo", "version": "1.0", "vulns": [{"id": "CVE-example", "fix_versions": ["1.1"]}]}]}))
    monkeypatch.setattr("sentinel.checks.runner.subprocess.run", execute)
    result = audit_dependencies(tmp_path, "requirements-audit.txt", 5)
    assert result.status == "failed"
    assert result.issues[0].rule == "CVE-example"


def test_bad_audit_json_is_error(tmp_path, monkeypatch):
    (tmp_path / "requirements-audit.txt").write_text("demo==1.0")
    monkeypatch.setattr("sentinel.checks.runner.subprocess.run", lambda *a, **k: SimpleNamespace(returncode=0, stderr=b"", stdout=b"{}"))
    assert audit_dependencies(tmp_path, "requirements-audit.txt", 5).status == "error"


def test_type_diagnostics_keep_locations_not_raw_messages(tmp_path, monkeypatch):
    def execute(command, **kwargs):
        kwargs["stdout"].write(b'src/app.py:12: error: secret literal [arg-type]\n')
        return SimpleNamespace(returncode=1)
    monkeypatch.setattr("sentinel.checks.runner.subprocess.run", execute)
    result = container_check("types", tmp_path, "prepared:local", 5)
    assert result.issues[0].path == "src/app.py"
    assert result.issues[0].line == 12
    assert result.issues[0].rule == "arg-type"
    assert "secret literal" not in result.model_dump_json()


def test_symlink_directory_is_incomplete(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    target = tmp_path / "project"
    target.mkdir()
    try:
        (target / "linked").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Symlink permission unavailable")
    assert run_checks(target, ["secrets"]).results[0].status == "incomplete"


def test_lint_diagnostics_keep_locations(tmp_path, monkeypatch):
    def execute(command, **kwargs):
        kwargs["stdout"].write(json.dumps([{"code": "F821", "filename": "/tmp/project/app.py", "location": {"row": 3}, "message": "secret literal"}]).encode())
        return SimpleNamespace(returncode=1)
    monkeypatch.setattr("sentinel.checks.runner.subprocess.run", execute)
    result = container_check("lint", tmp_path, "prepared:local", 5)
    assert result.status == "failed"
    assert result.issues[0].path == "app.py"
    assert result.issues[0].line == 3
    assert "secret literal" not in result.model_dump_json()


@pytest.mark.parametrize("name", ["lint", "types", "tests", "build"])
def test_daemon_connection_error_is_not_a_target_failure(tmp_path, monkeypatch, name):
    def execute(command, **kwargs):
        kwargs["stdout"].write(b"failed to connect to the docker API at npipe: missing engine")
        return SimpleNamespace(returncode=1)
    monkeypatch.setattr("sentinel.checks.runner.subprocess.run", execute)
    result = container_check(name, tmp_path, "prepared:local", 5)
    assert result.status == "incomplete"
    assert "no target check ran" in result.summary
