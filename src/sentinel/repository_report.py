"""Render repository review without PR hunk anchors or automatic approvals."""

from sentinel.quality.render import render_quality, append_quality_sarif

from sentinel.agents.consolidator import generate_sarif
from sentinel.state import ConsolidatedReport, PRReviewState, ReviewOutcome, Severity


def repository_consolidator_node(state: PRReviewState) -> dict:
    inventory = state["repository_inventory"]
    assessment = state["project_assessment"]
    findings = sorted(state["verified_findings"], key=lambda f: (
        list(Severity).index(f.severity), f.file_path, f.start_line, f.title,
    ))
    blocking = any(f.severity in {Severity.HIGH, Severity.CRITICAL} for f in findings)
    if blocking:
        outcome = ReviewOutcome.CHANGES_REQUIRED
    elif inventory.uninspected_files or not inventory.analyzed_files or (state.get("quality_review") and not state["quality_review"].complete):
        outcome = ReviewOutcome.INCOMPLETE_REVIEW
    else:
        outcome = ReviewOutcome.CLEAN
    lines = [
        "# SentinelPR Repository Review", "", f"**Project:** `{inventory.root}`", "",
        f"**Outcome:** `{outcome.value}`", "",
        "## Scope and coverage", "",
        f"- Python files statically analyzed: **{len(inventory.analyzed_files)}**",
        f"- Project context files read: **{len(inventory.context_files)}**",
        f"- Excluded inventory entries: **{len(inventory.excluded_files)}**",
        f"- Relevant files not inspected: **{len(inventory.uninspected_files)}**",
        "- Git-ignored files are outside the inventory; plain directories use built-in exclusions.",
        "- CLEAN means no blocking findings from the supported checks, not production approval.",
        "",
    ]
    if not inventory.analyzed_files:
        lines += ["**Incomplete code review:** No Python files were available for analysis.", ""]
    if assessment.llm_summary:
        lines += ["## Model assessment (static context only; excludes executable validation)", "", assessment.llm_summary, ""]
    lines += ["## Strengths", ""]
    lines += [f"- {item}" for item in assessment.strengths] or ["No structural strengths identified by the available checks."]
    lines += ["", "## Code findings", ""]
    if not findings:
        lines += ["No findings retained by the supported static checks.", ""]
    for finding in findings:
        lines += [
            f"### [{finding.severity.value}] {finding.title}", "",
            f"**Location:** `{finding.file_path}:{finding.start_line}-{finding.end_line}`  ",
            f"**Category:** {finding.category.value} | **Evidence:** {finding.evidence_source.value} | **Proof:** {finding.proof_status.value}", "",
            "**Classification:** Advisory hypothesis" if finding.hypothesis else "**Classification:** Retained with recorded proof status", "",
            finding.explanation, "",
        ]
        guidance = finding.remediation_guidance or finding.suggested_fix
        if guidance:
            lines += [f"**Advice:** {guidance}", ""]
        if finding.critic_reasoning:
            lines += [f"**Critic:** {finding.critic_reasoning}", ""]
    lines += ["## Project critiques and recommendations (advisory)", ""]
    if not assessment.advice:
        lines += ["No additional project recommendations from the available checks.", ""]
    for item in assessment.advice:
        lines += [f"### [{item.priority}] {item.title}", "", item.rationale, "", f"**Next step:** {item.recommendation}", ""]
        if item.evidence:
            lines += ["**Evidence:** " + ", ".join(f"`{p}`" for p in item.evidence), ""]
        lines += [f"**Source:** {item.source}", ""]
    lines += ["## Recommended next steps", ""]
    lines += [f"{i}. {item.recommendation}" for i, item in enumerate(assessment.advice[:5], 1)] or ["Maintain the existing regression checks and review changes incrementally."]
    lines += ["", "## Limitations", ""]
    lines += [f"- {item}" for item in assessment.limitations]
    if assessment.llm_context_files:
        lines += ["", "**Files included as model excerpts:** " + ", ".join(f"`{p}`" for p in assessment.llm_context_files)]
    lines += ["", "## Files not inspected", ""]
    lines += [f"- `{p}`: {reason}" for p, reason in inventory.uninspected_files.items()] or ["None within the supported inventory scope."]
    if inventory.excluded_files:
        lines += ["", "<details><summary>Excluded files</summary>", ""]
        lines += [f"- `{p}`: {reason}" for p, reason in inventory.excluded_files.items()]
        lines += ["", "</details>"]
    report = ConsolidatedReport(
        critic_limitations=state.get("critic_limitations", []),
        quality_review=state.get("quality_review"),
        summary_markdown="\n".join(lines) + "\n\n" + render_quality(state.get("quality_review")), review_outcome=outcome,
        sarif_json=append_quality_sarif(generate_sarif(findings), state.get("quality_review")), total_findings_count=len(state["candidate_findings"]),
        accepted_findings_count=len(findings), rejected_findings_count=len(state["candidate_findings"]) - len(findings),
        uninspected_files=list(inventory.uninspected_files), repository_inventory=inventory,
        project_assessment=assessment,
    )
    from sentinel.checks.report import refresh_executive_summary
    refresh_executive_summary(report)
    return {"consolidated_report": report, "review_outcome": outcome, "verified_findings": findings}
