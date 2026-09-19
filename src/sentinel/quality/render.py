"""Quality advice in Markdown and SARIF, separate from blocking code verdicts."""


from urllib.parse import quote

from html import escape


from sentinel.quality.ranking import group_observations, ranked_recommendations


def render_quality(review) -> str:
    if review is None:
        return ""
    lines = ["## Specialist code-quality review (advisory)", "",
        "**Checks:** " + ", ".join(review.specialists), "",
        f"**Snapshot:** `{review.snapshot_id[:12]}` | **Unresolved calls:** {review.unresolved_calls} | **Complete within supported scope:** {review.complete}", ""]
    if review.baseline:
        b = review.baseline
        lines += [f"**Baseline:** {b.new} new, {b.existing} existing, {len(b.resolved)} resolved, {len(b.unassessed)} unassessed.", ""]
    if not review.findings:
        lines += ["No observations from the implemented quality rules within the available scope.", ""]
    groups = group_observations(review.findings)
    if groups:
        recommendations = ranked_recommendations(review.contextual_advice)
        lines += ["### Suggested starting points", ""]
        if recommendations:
            lines += ["Ranked by model-estimated impact, confidence, then benefit, with cited reasons. These are advisory judgments, not verified defects.", ""]
            for item in recommendations[:3]:
                decision = item.decision
                assert decision is not None
                lines += [f"- <strong>{escape(item.subject)}</strong>: {escape(decision.recommendation)}",
                          f"  Impact: {decision.impact} — {escape(decision.impact_reason)}; confidence: {decision.confidence}; benefit: {decision.benefit} — {escape(decision.benefit_reason)}."]
        else:
            lines += ["No contextual change recommendation established. The following are static signals for inspection, ordered by rule priority, lifecycle, and overlap; this is not an estimate of engineering benefit.", ""]
            assessed = {fp for item in review.contextual_advice if item.status == "reviewed" for fp in item.fingerprints}
            pending = [group for group in groups if not any(f.fingerprint in assessed for f in group)]
            for group in pending[:3]:
                first = group[0]
                location = first.evidence[0].location
                lines += [f"- **{first.subject}** (`{location.file_path}:{location.start_line}`): " + "; ".join(f.title for f in group)]
        lines += ["", "<details>", "<summary>Full advisory inventory and evidence</summary>", ""]
        for group in groups:
            lines += [f"### [{group[0].priority}] {group[0].subject}", ""]
            lines += ["| Rule | Observation | Verification | Confidence | Status |", "| --- | --- | --- | --- | --- |"]
            for finding in group:
                lines += [f"| `{finding.rule_id}` | {escape(finding.title)} | {finding.verification_status} | {finding.confidence} | {finding.lifecycle} |"]
            lines += [""]
            for text in dict.fromkeys(f.explanation for f in group):
                lines += [text, ""]
            conditions = list(dict.fromkeys(f.trigger_conditions for f in group))
            lines += ["**Conditions:** " + "; ".join(conditions), "", "**Evidence:**"]
            evidence = dict.fromkeys((e.location.file_path, e.location.start_line, e.location.end_line, e.kind, e.source_hash) for f in group for e in f.evidence)
            lines += [f"- `{path}:{start}-{end}` ({kind}; source `{source_hash[:12]}`)" for path, start, end, kind, source_hash in evidence]
            lines += [""]
            assessment = next((item for item in review.contextual_advice if group[0].fingerprint in item.fingerprints), None)
            if assessment is None or assessment.status != "reviewed":
                lines += ["**Rule prompt (not contextually assessed):** " + " ".join(dict.fromkeys(f.recommendation for f in group)), ""]
            if assessment is not None:
                lines += render_contextual_advice(assessment)
        lines += ["</details>", ""]
    lines += ["Unresolved calls describe analyzer limitations; their count is not a defect count.", ""]
    lines += ["### Specialist limitations", ""]
    lines += [f"- {item}" for item in review.limitations]
    return "\n".join(lines) + "\n"



def render_contextual_advice(item) -> list[str]:
    lines = [f"**Contextual review:** {item.status}", ""]
    if item.selection_reason:
        lines += ["**Review selection:** " + escape(item.selection_reason), ""]
    if item.limitation:
        lines += [escape(item.limitation), ""]
    if item.decision is None:
        return lines
    decision = item.decision
    labels = {"keep": "Keep this implementation", "recommend": "Recommend a change", "inconclusive": "Insufficient evidence for an action"}
    lines += [f"**{labels[decision.disposition]}** (model opinion: {escape(item.model or '')})", "",
              escape(decision.rationale), ""]
    if decision.disposition == "recommend":
        lines += ["**Advice:** " + escape(decision.recommendation), "",
                  f"**Impact:** {decision.impact} — {escape(decision.impact_reason)}", "",
                  f"**Benefit:** {decision.benefit} — {escape(decision.benefit_reason)}; **Confidence:** {decision.confidence}", ""]
    lines += [f"- <code>{escape(c.file_path)}:{c.line}</code> (source <code>{item.context_hashes[c.file_path][:12]}</code>)" for c in decision.evidence]
    return [*lines, ""]



def quality_message(finding, assessment) -> str:
    if assessment is not None and assessment.decision is not None:
        decision = assessment.decision
        detail = decision.recommendation if decision.disposition == "recommend" else decision.rationale
        return finding.explanation + f" Contextual opinion ({decision.disposition}): " + detail
    return finding.explanation + " Rule prompt (not contextually assessed): " + finding.recommendation


def append_quality_sarif(sarif, review):
    if review is None:
        return sarif
    run = sarif["runs"][0]
    known = {rule["id"] for rule in run["tool"]["driver"]["rules"]}
    assessments = {fp: item for item in review.contextual_advice for fp in item.fingerprints}
    for finding in review.findings:
        if finding.rule_id not in known:
            known.add(finding.rule_id)
            run["tool"]["driver"]["rules"].append({"id": finding.rule_id, "shortDescription": {"text": finding.title}})
        run["results"].append({
            "ruleId": finding.rule_id, "level": "note",
            "message": {"text": quality_message(finding, assessments.get(finding.fingerprint))},
            "partialFingerprints": {"sentinelQuality/v1": finding.fingerprint},
            "baselineState": "unchanged" if finding.lifecycle == "existing" else "new",
            "properties": {"advisory": True, "category": finding.category, "verification": finding.verification_status,
                "confidence": finding.confidence, "snapshot": review.snapshot_id, "rulePrompt": finding.recommendation,
                "contextualReview": assessments[finding.fingerprint].model_dump(mode="json") if finding.fingerprint in assessments else None},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": quote(e.location.file_path, safe="/")},
                "region": {"startLine": e.location.start_line, "endLine": e.location.end_line}}} for e in finding.evidence],
        })
    return sarif
