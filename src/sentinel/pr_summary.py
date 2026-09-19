"""Small GitHub review; complete evidence stays in the report artifacts."""
from collections import Counter
from html import escape
from sentinel.quality.ranking import ranked_recommendations


def brief(text, limit=280):
    text = " ".join(text.split())
    return escape(text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…")


def render_pr_summary(report, head, artifact_url=None):
    lines = ["## SentinelPR review", "", f"**Outcome: {report.review_outcome.value}** · {report.accepted_findings_count} retained finding(s).",
             "CLEAN means no blocking findings within supported checks, not merge approval.", ""]
    if report.validation:
        lines += ["**Validation:** " + "; ".join(f"{r.name}: **{r.status}**" for r in report.validation.results) + "."]
        for check in report.validation.results:
            if check.status != "passed":
                lines += [f"- {check.name}: {brief(check.summary)}"]
    else:
        lines += ["**Validation:** not run."]
    lines += ["Measured test coverage: unavailable.", ""]
    if report.inline_comments:
        lines += [f"**Code findings:** {len(report.inline_comments)} location-specific finding(s) in the diff comments.", ""]
    if report.out_of_hunk_notes:
        lines += ["### Findings outside the diff", ""]
        for note in report.out_of_hunk_notes[:5]:
            lines += [f"- <code>{escape(note['path'])}:{note['line']}</code>: {brief(note['body'])}"]
        if len(report.out_of_hunk_notes) > 5:
            lines += [f"{len(report.out_of_hunk_notes) - 5} more in the full report."]
    review = report.quality_review
    if review:
        advice = ranked_recommendations(review.contextual_advice)
        if advice:
            lines += ["### Optional improvements", ""]
            for item in advice[:3]:
                assert item.decision is not None
                lines += [f"- **{escape(item.subject)}:** {brief(item.decision.recommendation)}"]
        counts = Counter(item.status for item in review.contextual_advice)
        reviewed = counts["reviewed"]
        kept = sum(item.decision is not None and item.decision.disposition == "keep" for item in review.contextual_advice)
        lines += ["", f"**Contextual coverage:** {reviewed}/{len(review.contextual_advice)} selected groups assessed; {kept} assessed groups need no change.",
                  f"Static scope complete: {review.complete}. {review.unresolved_calls} unresolved calls are analyzer limitations, not defects."]
        if counts:
            lines += ["Assessment status: " + ", ".join(f"{name}: {count}" for name, count in sorted(counts.items())) + "."]
        if not review.contextual_advice:
            lines += ["Contextual advice was not performed or had no eligible groups."]
    if report.uninspected_files:
        lines += [f"**Uninspected files:** {len(report.uninspected_files)}; see full report for paths and limitations."]
    audits = Counter(a.decision for a in report.critic_audit)
    if audits:
        lines += ["**Critic audit:** " + ", ".join(f"{key.lower()}: {value}" for key, value in sorted(audits.items())) + "."]
    if report.llm_usage:
        states = Counter(c["status"] for c in report.llm_usage)
        lines += ["**Model execution:** " + ", ".join(f"{key}: {value}" for key, value in sorted(states.items())) + "."]
    lines += ["", f"Reviewed commit `{head}`."]
    if artifact_url:
        lines += [f"[Full report, evidence, critic audit and JSON/SARIF exports]({artifact_url}) — download **sentinel-pr-review** under Artifacts when the workflow finishes."]
    else:
        lines += ["Full evidence and limitations: review.md, review.json and review.sarif in the configured report directory."]
    return "\n".join(lines) + "\n"
