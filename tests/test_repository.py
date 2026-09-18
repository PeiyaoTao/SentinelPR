"""Repository review integration and perimeter regressions; all model calls are mocked."""

import json
from pathlib import Path
import shutil
import subprocess
from unittest.mock import Mock

import pytest

from sentinel import cli
from sentinel.agents.project import _project_context
from sentinel.config import SentinelConfig, default_config
from sentinel.graph import review_repository
from sentinel.repository import collect_repository, repository_symbols
from sentinel.state import FindingCategory, ReviewOutcome, TrustZone


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(default_config, "provider", "heuristics")
    monkeypatch.setenv("SENTINEL_LLM_PROVIDER", "heuristics")


def write(root, name, content):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_review_unchanged_code_without_execution(tmp_path, monkeypatch):
    marker = tmp_path / "must_not_exist"
    write(tmp_path, "core.py", f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n\ndef collect(items=[]):\n    return items\n")
    write(tmp_path, "README.md", "# Example\n")
    monkeypatch.setattr("sentinel.harness.sandbox.execute_test_script", Mock(side_effect=AssertionError("must not execute")))
    state = review_repository(tmp_path)
    report = state["consolidated_report"]
    assert not marker.exists()
    finding = next(f for f in state["verified_findings"] if "Mutable Default" in f.title)
    assert finding.start_line == 4
    assert finding.reproduction_script is None
    assert report.review_outcome == ReviewOutcome.CLEAN
    assert finding.hypothesis
    assert report.inline_comments == []
    assert report.out_of_hunk_notes == []
    assert "Repository Review" in report.summary_markdown
    assert finding.explanation in report.summary_markdown
    assert "Project critiques" in report.summary_markdown
    assert report.project_assessment.strengths
    assert report.sarif_json["runs"][0]["results"]
    assert state["diff"] == ""


def test_top_level_secret_and_class_method_locations(tmp_path):
    write(tmp_path, "core.py", "# Header\n\napi_key = 'abcdefghijklmnop1234'\n\nclass Store:\n    def get(self, items=[]):\n        return items\n")
    state = review_repository(tmp_path)
    locations = [(f.category, f.start_line) for f in state["verified_findings"]]
    assert (FindingCategory.SECURITY, 3) in locations
    assert (FindingCategory.LOGIC, 6) in locations
    assert locations.count((FindingCategory.LOGIC, 6)) == 1


def test_route_decorator_keeps_boundary_and_line_numbers():
    content = "# header\n@app.route('/x')\ndef handler(request: Request):\n    if request is None:\n        return 0\n    return 1\n"
    scopes = repository_symbols("app.py", content)
    assert len(scopes) == 1
    assert scopes[0].start_line == 2
    assert scopes[0].trust_zone == TrustZone.PERIMETER
    assert scopes[0].code_snippet.startswith("@app.route")


def test_no_repository_or_diff_needed_and_advice_does_not_block(tmp_path):
    write(tmp_path, "core.py", "def add(a, b):\n    return a + b\n")
    report = review_repository(tmp_path)["consolidated_report"]
    assert report.review_outcome == ReviewOutcome.CLEAN
    assert any(a.priority == "high" for a in report.project_assessment.advice)
    assert report.sarif_json["runs"][0]["results"] == []


def test_unsupported_and_invalid_source_are_disclosed(tmp_path):
    write(tmp_path, "ok.py", "value = 1\n")
    write(tmp_path, "broken.py", "def invalid(\n")
    write(tmp_path, "ui.ts", "export const n = 1;\n")
    report = review_repository(tmp_path)["consolidated_report"]
    assert report.review_outcome == ReviewOutcome.INCOMPLETE_REVIEW
    assert set(report.uninspected_files) == {"broken.py", "ui.ts"}
    assert report.repository_inventory.analyzed_files == ["ok.py"]
    assert "SyntaxError" in report.summary_markdown


def test_blocking_findings_do_not_hide_incomplete_coverage(tmp_path):
    write(tmp_path, "core.py", "api_key = 'abcdefghijklmnop1234'\n")
    write(tmp_path, "ui.ts", "export const n = 1;\n")
    report = review_repository(tmp_path)["consolidated_report"]
    assert report.review_outcome == ReviewOutcome.CHANGES_REQUIRED
    assert report.uninspected_files == ["ui.ts"]
    assert "ui.ts" in report.summary_markdown


@pytest.mark.parametrize("setting,value,reason", [
    ("repository_max_files", 1, "file budget"),
    ("repository_max_file_bytes", 5, "per-file byte budget"),
    ("repository_max_total_bytes", 15, "repository byte budget"),
])
def test_budget_omissions_are_explicit(tmp_path, setting, value, reason):
    write(tmp_path, "a.py", "value = 1\n")
    write(tmp_path, "b.py", "value = 2\n")
    inventory, contents = collect_repository(tmp_path, SentinelConfig(**{setting: value}))
    assert any(reason in item for item in inventory.uninspected_files.values())
    assert "b.py" not in contents


def test_empty_or_documentation_only_directory_is_incomplete(tmp_path):
    write(tmp_path, "README.md", "# Documentation only\n")
    report = review_repository(tmp_path)["consolidated_report"]
    assert report.review_outcome == ReviewOutcome.INCOMPLETE_REVIEW
    assert "No Python files" in report.summary_markdown


def test_secrets_and_dependency_directories_are_not_read(tmp_path):
    write(tmp_path, "core.py", "value = 1\n")
    write(tmp_path, ".env", "API_KEY=do-not-read\n")
    write(tmp_path, "node_modules/pkg/bad.py", "raise RuntimeError()\n")
    inventory, contents = collect_repository(tmp_path, SentinelConfig())
    assert set(contents) == {"core.py"}
    assert ".env" in inventory.excluded_files


def test_python_encoding_cookie_supported(tmp_path):
    (tmp_path / "encoded.py").write_bytes(b"# coding: latin-1\nname = 'caf\xe9'\n")
    inventory, contents = collect_repository(tmp_path, SentinelConfig())
    assert inventory.analyzed_files == ["encoded.py"]
    assert "caf\u00e9" in contents["encoded.py"]


def test_links_are_not_followed(tmp_path):
    target = write(tmp_path, "real.py", "value = 1\n")
    try:
        (tmp_path / "link.py").symlink_to(target)
    except OSError:
        pytest.skip("Symlink creation unavailable for this account")
    inventory, contents = collect_repository(tmp_path, SentinelConfig())
    assert "link.py" not in contents
    assert "link.py" in inventory.uninspected_files


def test_git_inventory_includes_untracked_and_honors_ignores(tmp_path):
    if not shutil.which("git"):
        pytest.skip("Git not installed")
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    write(tmp_path, ".gitignore", "ignored.py\n")
    write(tmp_path, "tracked.py", "value = 1\n")
    write(tmp_path, "untracked.py", "value = 2\n")
    write(tmp_path, "ignored.py", "value = 3\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "tracked.py"], check=True, capture_output=True)
    inventory, contents = collect_repository(tmp_path, SentinelConfig())
    assert set(contents) == {"tracked.py", "untracked.py"}
    assert "ignored.py" not in inventory.files


def test_test_filename_presence_is_not_substring_match(tmp_path):
    write(tmp_path, "contest.py", "value = 1\n")
    report = review_repository(tmp_path)["consolidated_report"]
    assert any(a.title == "Establish a regression-test baseline" for a in report.project_assessment.advice)


def test_model_assessment_is_grounded_advisory_and_bounded(tmp_path, monkeypatch):
    write(tmp_path, "core.py", "def add(a, b): return a + b\n")
    monkeypatch.setattr(default_config, "provider", "ollama")
    client = Mock()
    client.complete.return_value = json.dumps({
        "summary": "The inspected helper is small; delivery validation needs attention.",
        "advice": [{"title": "Specify the input contract", "priority": "medium", "rationale": "The helper has no annotations.", "recommendation": "Document accepted operands.", "evidence": ["core.py"]}],
    })
    monkeypatch.setattr("sentinel.agents.project.get_llm_client", lambda **kwargs: client)
    state = review_repository(tmp_path)
    report = state["consolidated_report"]
    assert report.review_outcome == ReviewOutcome.CLEAN
    assert report.project_assessment.advice[-1].source in {"heuristic", "llm"}
    assert any(a.source == "llm" for a in report.project_assessment.advice)
    assert "Specify the input contract" in report.summary_markdown
    assert report.sarif_json["runs"][0]["results"] == []
    messages = client.complete.call_args.args[0]
    assert messages[0]["role"] == "system"
    assert "untrusted data" in messages[0]["content"]
    assert len(messages[1]["content"]) <= default_config.repository_llm_context_chars
    assert client.complete.call_count == 1
    payload, included = _project_context(state, 1000)
    assert len(payload) <= 1000
    assert included == ["core.py"]


@pytest.mark.parametrize("response", ["not json", '{"summary":"ok","advice":[{"title":"fake","priority":"high","rationale":"fake","recommendation":"fake","evidence":["absent.py"]}]}'])
def test_invalid_model_evidence_is_disclosed_not_published(tmp_path, monkeypatch, response):
    write(tmp_path, "core.py", "value = 1\n")
    monkeypatch.setattr(default_config, "provider", "ollama")
    client = Mock()
    client.complete.return_value = response
    monkeypatch.setattr("sentinel.agents.project.get_llm_client", lambda **kwargs: client)
    report = review_repository(tmp_path)["consolidated_report"]
    assert report.project_assessment.llm_summary is None
    assert all(a.source == "heuristic" for a in report.project_assessment.advice)
    assert "Model assessment unavailable" in report.summary_markdown


def test_cli_repository_exports_and_exit_code(tmp_path, monkeypatch, capsys):
    write(tmp_path, "core.py", "api_key = 'abcdefghijklmnop1234'\n")
    markdown, sarif = tmp_path / "report.md", tmp_path / "report.sarif"
    monkeypatch.setattr("sys.argv", ["sentinel", "--repo", str(tmp_path), "--provider", "heuristics", "--markdown", str(markdown), "--sarif", str(sarif)])
    with pytest.raises(SystemExit) as result:
        cli.main()
    assert result.value.code == 1
    assert "Repository Review" in capsys.readouterr().out
    assert "Project critiques" in markdown.read_text(encoding="utf-8")
    assert json.loads(sarif.read_text())["version"] == "2.1.0"


def test_cli_repo_modes_are_mutually_exclusive(monkeypatch):
    monkeypatch.setattr("sys.argv", ["sentinel", "--repo", ".", "--git"])
    with pytest.raises(SystemExit) as result:
        cli.main()
    assert result.value.code == 2


def test_cli_nonexistent_project_reports_infrastructure_failure(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["sentinel", "--repo", str(tmp_path / "missing")])
    with pytest.raises(SystemExit) as result:
        cli.main()
    assert result.value.code == 3
    assert "Repository review failed" in capsys.readouterr().err
