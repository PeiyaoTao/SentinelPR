"""
GitHub Actions PR Auto-Reviewer Integration.
Fetches PR diff via GitHub API, executes SentinelPR review, and submits
an automated review with inline comments and suggested code changes.
"""

import json
import os
import sys
from typing import Any, Dict, List
import requests

from sentinel.graph import review_pr
from sentinel.state import Severity


def run_github_auto_review():
    """Entrypoint for GitHub Actions automated pull request quality gate."""
    token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPOSITORY")
    event_path = os.getenv("GITHUB_EVENT_PATH")

    if not token or not repo or not event_path:
        sys.stderr.write("Error: GITHUB_TOKEN, GITHUB_REPOSITORY, and GITHUB_EVENT_PATH must be set.\n")
        sys.exit(1)

    with open(event_path, "r", encoding="utf-8") as f:
        event = json.load(f)

    pr = event.get("pull_request")
    if not pr:
        print("Not a pull request event. Skipping SentinelPR review.")
        return

    pr_number = pr["number"]
    pr_head_sha = pr["head"]["sha"]
    print(f"Running SentinelPR on {repo} PR #{pr_number} (Commit: {pr_head_sha})...")

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3.diff",
    }

    # Fetch PR unified diff
    diff_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    diff_resp = requests.get(diff_url, headers=headers, timeout=30)
    diff_resp.raise_for_status()
    diff_text = diff_resp.text

    # Fetch changed file contents from head workspace
    files_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files"
    files_resp = requests.get(files_url, headers={"Authorization": f"token {token}"}, timeout=30)
    files_resp.raise_for_status()
    changed_files = files_resp.json()

    head_files: Dict[str, str] = {}
    for f in changed_files:
        filename = f.get("filename")
        if filename and os.path.exists(filename) and os.path.isfile(filename):
            try:
                with open(filename, "r", encoding="utf-8", errors="replace") as fh:
                    head_files[filename] = fh.read()
            except Exception:
                pass

    # Run SentinelPR review
    result = review_pr(diff=diff_text, head_files=head_files)
    report = result.get("consolidated_report")
    verified_findings = result.get("verified_findings", [])

    if not report:
        print("Review completed with no report generated.")
        return

    # Construct GitHub Review Payload
    comments: List[Dict[str, Any]] = []
    for comment in report.inline_comments:
        comments.append({
            "path": comment["path"],
            "line": comment["line"],
            "side": comment.get("side", "RIGHT"),
            "body": comment["body"],
        })

    # Determine GitHub Review Event
    has_severe = any(f.severity in [Severity.CRITICAL, Severity.HIGH] for f in verified_findings)
    if has_severe:
        event_type = "REQUEST_CHANGES"
    elif verified_findings:
        event_type = "COMMENT"
    else:
        event_type = "APPROVE"

    review_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews"
    review_payload = {
        "commit_id": pr_head_sha,
        "body": report.summary_markdown,
        "event": event_type,
        "comments": comments,
    }

    submit_resp = requests.post(
        review_url,
        json=review_payload,
        headers={"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"},
        timeout=30,
    )

    if submit_resp.status_code in [200, 201]:
        print(f"Successfully posted SentinelPR review to PR #{pr_number} (Status: {event_type})")
    else:
        sys.stderr.write(f"Failed to post review: {submit_resp.status_code} {submit_resp.text}\n")
        # Fallback: post general issue comment if inline comments fail on hunk mismatch
        fallback_url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
        requests.post(
            fallback_url,
            json={"body": report.summary_markdown},
            headers={"Authorization": f"token {token}"},
            timeout=30,
        )


if __name__ == "__main__":
    run_github_auto_review()
