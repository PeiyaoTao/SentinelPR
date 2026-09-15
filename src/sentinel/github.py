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
from sentinel.state import ReviewOutcome, Severity


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

    # Fetch all changed files with pagination
    changed_files: List[Dict[str, Any]] = []
    page = 1
    api_headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    while True:
        files_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files?page={page}&per_page=100"
        files_resp = requests.get(files_url, headers=api_headers, timeout=30)
        files_resp.raise_for_status()
        data = files_resp.json()
        if not data:
            break
        changed_files.extend(data)
        if len(data) < 100 or "next" not in files_resp.links:
            break
        page += 1

    head_files: Dict[str, str] = {}
    uninspected_files: List[str] = []
    for f in changed_files:
        filename = f.get("filename")
        if not filename:
            continue
        if os.path.exists(filename) and os.path.isfile(filename):
            try:
                with open(filename, "r", encoding="utf-8", errors="replace") as fh:
                    head_files[filename] = fh.read()
            except (OSError, UnicodeDecodeError) as e:
                sys.stderr.write(f"Warning: Could not read head file '{filename}': {e}\n")
                uninspected_files.append(filename)
        else:
            if f.get("status") != "removed":
                uninspected_files.append(filename)

    # Run SentinelPR review
    result = review_pr(diff=diff_text, head_files=head_files, uninspected_files=uninspected_files)
    report = result.get("consolidated_report")
    verified_findings = result.get("verified_findings", [])

    if not report:
        sys.stderr.write("Review completed with no report generated.\n")
        sys.exit(3)

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
        headers=api_headers,
        timeout=30,
    )

    published = False
    if submit_resp.status_code in [200, 201]:
        print(f"Successfully posted SentinelPR review to PR #{pr_number} (Status: {event_type})")
        published = True
    else:
        sys.stderr.write(f"Failed to post review: {submit_resp.status_code} {submit_resp.text}\n")
        # Fallback: post general issue comment if inline comments fail on hunk mismatch
        fallback_url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
        fb_resp = requests.post(
            fallback_url,
            json={"body": report.summary_markdown},
            headers=api_headers,
            timeout=30,
        )
        if fb_resp.status_code in [200, 201]:
            print(f"Posted fallback review comment to PR #{pr_number}")
            published = True
        else:
            sys.stderr.write(f"Failed to post fallback comment: {fb_resp.status_code} {fb_resp.text}\n")

    if not published:
        sys.stderr.write("Fatal: Failed to publish review via both review API and issue comment fallback.\n")
        sys.exit(3)

    # Process exit outcome mapped to CI
    if report.review_outcome == ReviewOutcome.CHANGES_REQUIRED:
        sys.exit(1)
    elif report.review_outcome == ReviewOutcome.INCOMPLETE_REVIEW:
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == "__main__":
    run_github_auto_review()
