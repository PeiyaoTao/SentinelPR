"""Regression tests use real Git commits, never the checked-out file contents."""
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
from sentinel.git_snapshot import load_pr_snapshot
from sentinel.github import review_event, run_github_auto_review
from sentinel.state import ConsolidatedReport, ReviewOutcome


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "app.py").write_text("value = 1\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "base")
    base = git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "app.py").write_text("value = 2\n")
    git(tmp_path, "commit", "-am", "head")
    head = git(tmp_path, "rev-parse", "HEAD")
    return tmp_path, base, head


@pytest.mark.parametrize("outcome,expected", [
    (ReviewOutcome.CLEAN, "APPROVE"),
    (ReviewOutcome.INCOMPLETE_REVIEW, "COMMENT"),
    (ReviewOutcome.INFRASTRUCTURE_FAILURE, "COMMENT"),
    (ReviewOutcome.CHANGES_REQUIRED, "REQUEST_CHANGES"),
])
def test_outcome_controls_github_event(outcome, expected):
    assert review_event(outcome) == expected
    assert review_event(ReviewOutcome.CLEAN, True) == "COMMENT"


def test_immutable_sources_and_merge_base(repo):
    root, base, head = repo
    git(root, "checkout", "-b", "advanced-base", base)
    (root / "app.py").write_text("value = 99\n")
    git(root, "commit", "-am", "advance base")
    advanced = git(root, "rev-parse", "HEAD")
    (root / "app.py").write_text("value = 'dirty working tree'\n")
    snapshot = load_pr_snapshot(root, advanced, head)
    assert snapshot.merge_base == base
    assert snapshot.base_files["app.py"] == "value = 1\n"
    assert snapshot.head_files["app.py"] == "value = 2\n"
    assert "+value = 2" in snapshot.diff
    assert "99" not in snapshot.diff


def configure(monkeypatch, tmp_path, repo):
    root, base, head = repo
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"number": 1, "head": {"sha": head}, "base": {"sha": base}}}))
    for key, value in {"GITHUB_TOKEN": "test", "GITHUB_REPOSITORY": "owner/repo", "GITHUB_EVENT_PATH": str(event), "SENTINEL_TARGET_PATH": str(root), "SENTINEL_REPORT_DIR": str(tmp_path / "artifacts"), "SENTINEL_CHECKS": ""}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr("sentinel.github_comments.requests.get", lambda *a, **k: SimpleNamespace(raise_for_status=lambda: None, json=lambda: []))
    return head, base


def test_incomplete_posts_comment_and_returns_two(monkeypatch, tmp_path, repo):
    configure(monkeypatch, tmp_path, repo)
    monkeypatch.setattr("sentinel.github._current_revision", lambda *a: True)
    report = ConsolidatedReport(summary_markdown="Incomplete", review_outcome=ReviewOutcome.INCOMPLETE_REVIEW)
    monkeypatch.setattr("sentinel.github.review_pr", lambda *a, **k: {"consolidated_report": report, "verified_findings": []})
    posts = []
    monkeypatch.setattr("sentinel.github.requests.post", lambda *a, **k: posts.append(k["json"]) or SimpleNamespace(status_code=201))
    with pytest.raises(SystemExit) as result:
        run_github_auto_review()
    assert result.value.code == 2
    assert posts[0]["event"] == "COMMENT"
    assert (tmp_path / "artifacts" / "review.sarif").exists()


def test_changed_pr_never_publishes(monkeypatch, tmp_path, repo):
    configure(monkeypatch, tmp_path, repo)
    current = iter([True, False])
    monkeypatch.setattr("sentinel.github._current_revision", lambda *a: next(current))
    monkeypatch.setattr("sentinel.github.review_pr", lambda *a, **k: {"consolidated_report": ConsolidatedReport(summary_markdown="clean")})
    monkeypatch.setattr("sentinel.github.requests.post", lambda *a, **k: pytest.fail("Stale review was published"))
    with pytest.raises(SystemExit) as result:
        run_github_auto_review()
    assert result.value.code == 2


def test_fork_can_export_without_write_token(monkeypatch, tmp_path, repo):
    configure(monkeypatch, tmp_path, repo)
    monkeypatch.setenv("SENTINEL_PUBLISH", "false")
    monkeypatch.setattr("sentinel.github._current_revision", lambda *a: True)
    monkeypatch.setattr("sentinel.github.review_pr", lambda *a, **k: {"consolidated_report": ConsolidatedReport(summary_markdown="clean")})
    monkeypatch.setattr("sentinel.github.requests.post", lambda *a, **k: pytest.fail("Read-only run tried publishing"))
    with pytest.raises(SystemExit) as result:
        run_github_auto_review()
    assert result.value.code == 0
    assert (tmp_path / "artifacts" / "review.json").exists()


def test_invalid_revision_is_rejected(repo):
    root, base, _ = repo
    with pytest.raises(ValueError):
        load_pr_snapshot(root, base, "HEAD")
