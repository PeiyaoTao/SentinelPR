"""Merge executable validation results into the review outcome and exports."""
from urllib.parse import quote
from html import escape
from typing import Any
from sentinel.checks.models import ValidationReport
from sentinel.state import ConsolidatedReport, ReviewOutcome


def attach_validation(report: ConsolidatedReport, validation: ValidationReport) -> None:
    report.validation = validation
    previous = report.review_outcome
    statuses = {r.status for r in validation.results}
    if "error" in statuses or previous == ReviewOutcome.INFRASTRUCTURE_FAILURE:
        report.review_outcome = ReviewOutcome.INFRASTRUCTURE_FAILURE
    elif "failed" in statuses or previous == ReviewOutcome.CHANGES_REQUIRED:
        report.review_outcome = ReviewOutcome.CHANGES_REQUIRED
    elif "incomplete" in statuses or previous == ReviewOutcome.INCOMPLETE_REVIEW:
        report.review_outcome = ReviewOutcome.INCOMPLETE_REVIEW
    report.summary_markdown = report.summary_markdown.replace(previous.value, report.review_outcome.value)
    lines = ["", "## Project validation", "", f"**Final outcome:** {report.review_outcome.value}", "", f"Snapshot: `{validation.snapshot_id}`", "", "| Check | Status | Summary |", "| --- | --- | --- |"]
    results = []
    details = []
    for check in validation.results:
        lines.append(f"| {check.name} | {check.status} | {check.summary} |")
        for issue in check.issues[:50]:
            location = f"{issue.path}:{issue.line}" if issue.path else check.name
            details.append(f"- <code>{escape(location)}</code> — <code>{escape(issue.rule)}</code>: {escape(issue.message)}")
        if len(check.issues) > 50:
            details.append(f"- {check.name}: {len(check.issues) - 50} additional diagnostics are in SARIF/JSON.")
        for issue in check.issues:
            entry: dict[str, Any] = {"ruleId": f"sentinel/{check.name}/{issue.rule}", "level": "error", "message": {"text": issue.message}}
            if issue.path and issue.line:
                entry["locations"] = [{"physicalLocation": {"artifactLocation": {"uri": quote(issue.path, safe="/")}, "region": {"startLine": issue.line}}}]
            results.append(entry)
        if check.status != "passed" and not check.issues:
            results.append({"ruleId": f"sentinel/{check.name}", "level": "error" if check.status == "failed" else "warning", "message": {"text": check.summary}})
    if details:
        lines.extend(["", "### Validation diagnostics", "", *details])
    report.summary_markdown += "\n".join(lines) + "\n"
    report.sarif_json.setdefault("version", "2.1.0")
    report.sarif_json.setdefault("runs", []).append({
        "tool": {"driver": {"name": "SentinelPR validation"}}, "results": results,
        "invocations": [{"executionSuccessful": not bool(statuses & {"error", "incomplete"})}],
    })
