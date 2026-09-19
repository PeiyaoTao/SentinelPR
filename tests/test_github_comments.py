"""Reuse only bot-owned current anchors and preserve unresolved coverage gaps."""
from types import SimpleNamespace
from sentinel.github_comments import comment_key, reconcile_comments


def test_updates_current_thread_and_creates_new_outdated_anchor(monkeypatch):
    comment = {"path": "app.py", "line": 4, "body": "### SentinelPR: Issue\nDetails"}
    key = comment_key(comment)
    existing = {"id": 7, "path": "app.py", "line": 4,
                "body": comment["body"] + f"\n<!-- sentinel-finding:{key} -->", "user": {"login": "github-actions[bot]"}}
    monkeypatch.setattr("sentinel.github_comments.requests.get", lambda *a, **k: SimpleNamespace(json=lambda: [existing], raise_for_status=lambda: None))
    patches = []
    monkeypatch.setattr("sentinel.github_comments.requests.patch", lambda *a, **k: patches.append(k["json"]) or SimpleNamespace(raise_for_status=lambda: None))
    assert reconcile_comments("https://api.github.com/repos/o/r/pulls/1", {}, [comment], "new", True) == []
    assert "Reviewed at `new`" in patches[0]["body"]
    existing["line"] = None
    assert len(reconcile_comments("https://api.github.com/repos/o/r/pulls/1", {}, [comment], "next", True)) == 1
    assert len(patches) == 1


def test_incomplete_run_does_not_retire_old_findings_or_touch_human_comments(monkeypatch):
    comment = {"path": "app.py", "line": 4, "body": "### SentinelPR: Issue"}
    body = f"<!-- sentinel-finding:{comment_key(comment)} -->"
    items = [{"id": 1, "body": body, "user": {"login": "github-actions[bot]"}},
             {"id": 2, "body": body, "user": {"login": "author"}}]
    monkeypatch.setattr("sentinel.github_comments.requests.get", lambda *a, **k: SimpleNamespace(json=lambda: items, raise_for_status=lambda: None))
    patches = []
    monkeypatch.setattr("sentinel.github_comments.requests.patch", lambda *a, **k: patches.append(a[0]) or SimpleNamespace(raise_for_status=lambda: None))
    url = "https://api.github.com/repos/o/r/pulls/1"
    reconcile_comments(url, {}, [], "new", False)
    assert patches == []
    reconcile_comments(url, {}, [], "new", True)
    assert patches == ["https://api.github.com/repos/o/r/pulls/comments/1"]
