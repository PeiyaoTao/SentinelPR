"""Merge executable validation results into the review outcome and exports."""
from urllib.parse import quote
from html import escape
from typing import Any
from sentinel.checks.models import ValidationReport
from sentinel.state import ConsolidatedReport, ReviewOutcome


def validation_outcome(previous: ReviewOutcome, validation: ValidationReport) -> ReviewOutcome:
    statuses = {r.status for r in validation.results}
    for status, outcome in (("error", ReviewOutcome.INFRASTRUCTURE_FAILURE),
                            ("failed", ReviewOutcome.CHANGES_REQUIRED),
                            ("incomplete", ReviewOutcome.INCOMPLETE_REVIEW)):
        if status in statuses or previous == outcome:
            return outcome
    return previous


def validation_markdown(validation: ValidationReport, outcome: ReviewOutcome) -> str:
    lines = ["", "## Project validation", "", f"**Final outcome:** {outcome.value}", "", f"Snapshot: `{validation.snapshot_id}`", "", "| Check | Status | Summary |", "| --- | --- | --- |"]
    details = []
    for check in validation.results:
        lines.append(f"| {check.name} | {check.status} | {check.summary} |")
        for issue in check.issues[:50]:
            location = f"{issue.path}:{issue.line}" if issue.path else check.name
            details.append(f"- <code>{escape(location)}</code> — <code>{escape(issue.rule)}</code>: {escape(issue.message)}")
        if len(check.issues) > 50:
            details.append(f"- {check.name}: {len(check.issues) - 50} additional diagnostics are in SARIF/JSON.")
    if details:
        lines.extend(["", "### Validation diagnostics", "", *details])
    return "\n".join(lines) + "\n"


def validation_sarif(validation: ValidationReport) -> dict[str, Any]:
    results = []
    for check in validation.results:
        for issue in check.issues:
            entry: dict[str, Any] = {"ruleId": f"sentinel/{check.name}/{issue.rule}", "level": "error", "message": {"text": issue.message}}
            if issue.path and issue.line:
                entry["locations"] = [{"physicalLocation": {"artifactLocation": {"uri": quote(issue.path, safe="/")}, "region": {"startLine": issue.line}}}]
            results.append(entry)
        if check.status != "passed" and not check.issues:
            results.append({"ruleId": f"sentinel/{check.name}", "level": "error" if check.status == "failed" else "warning", "message": {"text": check.summary}})
    return {
        "tool": {"driver": {"name": "SentinelPR validation"}}, "results": results,
        "invocations": [{"executionSuccessful": not any(r.status in {"error", "incomplete"} for r in validation.results)}],
    }


def refresh_executive_summary(report: ConsolidatedReport) -> None:
    """Replace our generated summary using recorded validation facts."""
    start, end = "<!-- sentinel-summary -->", "<!-- /sentinel-summary -->"
    facts = f"**Review summary:** {report.review_outcome.value}; {report.accepted_findings_count} retained code finding(s). "
    if report.validation is None:
        facts += "Project validation has not been run for this report. "
    else:
        facts += "Validation: " + (", ".join(f"{r.name}: {r.status}" for r in report.validation.results) or "no checks selected") + ". "
    facts += "Measured test coverage: unavailable. CLEAN means no blocking findings within the supported checks; it is not merge approval."
    block = start + "\n" + facts + "\n" + end
    text = report.summary_markdown
    if start in text:
        before, rest = text.split(start, 1)
        _, after = rest.split(end, 1)
        report.summary_markdown = before + block + after
    else:
        heading, separator, rest = text.partition("\n")
        report.summary_markdown = heading + "\n\n" + block + "\n\n" + rest


def attach_validation(report: ConsolidatedReport, validation: ValidationReport) -> None:
    report.validation = validation
    previous = report.review_outcome
    report.review_outcome = validation_outcome(previous, validation)
    report.summary_markdown = report.summary_markdown.replace(previous.value, report.review_outcome.value)
    report.summary_markdown += validation_markdown(validation, report.review_outcome)
    report.sarif_json.setdefault("version", "2.1.0")
    report.sarif_json.setdefault("runs", []).append(validation_sarif(validation))
    refresh_executive_summary(report)
