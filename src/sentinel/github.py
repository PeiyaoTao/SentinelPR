"""Review immutable PR commits and publish only a current, explicit outcome."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import requests

from sentinel.graph import review_pr
from sentinel.git_snapshot import load_pr_snapshot, materialize_commit
from sentinel.state import ReviewOutcome
from sentinel.pr_summary import render_pr_summary
from sentinel.github_comments import reconcile_comments

EXIT_CODES = {ReviewOutcome.CLEAN: 0, ReviewOutcome.CHANGES_REQUIRED: 1,
              ReviewOutcome.INCOMPLETE_REVIEW: 2, ReviewOutcome.INFRASTRUCTURE_FAILURE: 3}


def review_event(outcome: ReviewOutcome, has_findings: bool = False) -> str:
    if outcome == ReviewOutcome.CHANGES_REQUIRED:
        return "REQUEST_CHANGES"
    if outcome != ReviewOutcome.CLEAN or has_findings:
        return "COMMENT"
    return "APPROVE"


def _current_revision(url: str, headers: dict, head: str, base: str) -> bool:
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    current = response.json()
    return current["head"]["sha"] == head and current["base"]["sha"] == base and current["state"] == "open"


def run_github_auto_review():
    token, repo, event_path = (os.getenv(key) for key in ("GITHUB_TOKEN", "GITHUB_REPOSITORY", "GITHUB_EVENT_PATH"))
    if not token or not repo or not event_path:
        raise ValueError("GITHUB_TOKEN, GITHUB_REPOSITORY, and GITHUB_EVENT_PATH must be set")
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    pr = event.get("pull_request")
    if not pr:
        print("Not a pull request event. Skipping SentinelPR review.")
        return
    root = Path(os.environ.get("SENTINEL_TARGET_PATH", ".")).resolve()
    number, head, base = pr["number"], pr["head"]["sha"], pr["base"]["sha"]
    url = f"{os.environ.get('GITHUB_API_URL', 'https://api.github.com')}/repos/{repo}/pulls/{number}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    if not _current_revision(url, headers, head, base):
        print("PR revision changed or closed; refusing to review a stale event.")
        sys.exit(2)
    snapshot = load_pr_snapshot(root, base, head)
    result = review_pr(snapshot.diff, snapshot.head_files, base_files=snapshot.base_files, uninspected_files=snapshot.uninspected)
    report = result["consolidated_report"]
    checks = os.environ.get("SENTINEL_CHECKS", "")
    if checks:
        from sentinel.checks.models import CHECK_NAMES
        from sentinel.checks.runner import run_checks
        from sentinel.checks.report import attach_validation
        names = list(CHECK_NAMES) if checks == "all" else checks.split(",")
        with tempfile.TemporaryDirectory(prefix="sentinel-commit-") as directory:
            omitted = materialize_commit(root, head, Path(directory))
            validation = run_checks(directory, names, os.environ.get("SENTINEL_CHECK_IMAGE", "sentinel-checks:local"), requirements=os.environ.get("SENTINEL_REQUIREMENTS", "requirements-audit.txt"))
            if omitted:
                for check in validation.results:
                    if check.status == "passed":
                        check.status = "incomplete"
                    check.summary += f" Commit snapshot omitted {len(omitted)} files."
            attach_validation(report, validation)
    report.summary_markdown += f"\n\nReviewed commit `{head}` against merge base `{snapshot.merge_base}`.\n"
    output = Path(os.environ.get("SENTINEL_REPORT_DIR", "sentinel-artifacts"))
    output.mkdir(parents=True, exist_ok=True)
    from sentinel.html_report import render_html
    (output / "review.html").write_text(render_html(report), encoding="utf-8")
    (output / "review.md").write_text(report.summary_markdown, encoding="utf-8")
    (output / "review.sarif").write_text(json.dumps(report.sarif_json, indent=2), encoding="utf-8")
    (output / "review.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(f"SentinelPR result: {report.review_outcome.value}; exit code {EXIT_CODES[report.review_outcome]}; "
          f"retained findings={report.accepted_findings_count}; "
          f"model calls incomplete={sum(c['status'] not in {'completed', 'cached'} for c in report.llm_usage)}", flush=True)
    if report.validation:
        print("SentinelPR validation: " + ", ".join(f"{c.name}={c.status}" for c in report.validation.results), flush=True)
    print("Full report: " + str(output / "review.json"), flush=True)
    if not _current_revision(url, headers, head, base):
        print("PR revision changed or closed during analysis; report retained, publication skipped.")
        sys.exit(2)
    if os.environ.get("SENTINEL_PUBLISH", "true").lower() == "false":
        print("Publication disabled; review artifacts retained.")
        sys.exit(EXIT_CODES[report.review_outcome])
    run_id = os.environ.get("GITHUB_RUN_ID")
    artifact_url = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{repo}/actions/runs/{run_id}" if run_id else None
    body = render_pr_summary(report, head, artifact_url)
    event_type = review_event(report.review_outcome, bool(result.get("verified_findings")))
    comments = reconcile_comments(url, headers, report.inline_comments, head,
                                  report.review_outcome in {ReviewOutcome.CLEAN, ReviewOutcome.CHANGES_REQUIRED}
                                  and not report.uninspected_files
                                  and not any(c["status"] not in {"completed", "cached"} for c in report.llm_usage)
                                  and (report.quality_review is None or report.quality_review.complete),
                                  retained_notes=report.out_of_hunk_notes)
    payload = {"commit_id": head, "body": body, "event": event_type,
               "comments": [{"path": c["path"], "line": c["line"], "side": c.get("side", "RIGHT"), "body": c["body"]} for c in comments]}
    response = requests.post(url + "/reviews", json=payload, headers=headers, timeout=30)
    if response.status_code not in (200, 201):
        # A fallback comment is informational; CI still uses the review outcome.
        fallback = requests.post(url.replace(f"/pulls/{number}", f"/issues/{number}") + "/comments", json={"body": body}, headers=headers, timeout=30)
        fallback.raise_for_status()
    sys.exit(EXIT_CODES[report.review_outcome])


if __name__ == "__main__":
    try:
        run_github_auto_review()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, requests.RequestException) as error:
        # Do not print HTTP bodies or target output, which can contain secrets.
        print(f"GitHub review infrastructure failed ({type(error).__name__}).", file=sys.stderr)
        sys.exit(3)
