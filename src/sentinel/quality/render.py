"""Quality advice in Markdown and SARIF, separate from blocking code verdicts."""


from urllib.parse import quote

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
    for finding in review.findings:
        lines += [f"### [{finding.priority}] {finding.title}", "",
            f"**Rule:** `{finding.rule_id}` | **Verification:** {finding.verification_status} | **Confidence:** {finding.confidence} | **Status:** {finding.lifecycle}", "",
            finding.explanation, "", f"**Conditions:** {finding.trigger_conditions}", "",
            f"**Advice:** {finding.recommendation}", "", "**Evidence:**"]
        lines += [f"- `{e.location.file_path}:{e.location.start_line}-{e.location.end_line}` ({e.kind}; source `{e.source_hash[:12]}`)" for e in finding.evidence]
        lines += [""]
    lines += ["### Specialist limitations", ""]
    lines += [f"- {item}" for item in review.limitations]
    return "\n".join(lines) + "\n"


def append_quality_sarif(sarif, review):
    if review is None:
        return sarif
    run = sarif["runs"][0]
    known = {rule["id"] for rule in run["tool"]["driver"]["rules"]}
    for finding in review.findings:
        if finding.rule_id not in known:
            known.add(finding.rule_id)
            run["tool"]["driver"]["rules"].append({"id": finding.rule_id, "shortDescription": {"text": finding.title}})
        run["results"].append({
            "ruleId": finding.rule_id, "level": "note",
            "message": {"text": finding.explanation + " Advice: " + finding.recommendation},
            "partialFingerprints": {"sentinelQuality/v1": finding.fingerprint},
            "baselineState": "unchanged" if finding.lifecycle == "existing" else "new",
            "properties": {"advisory": True, "category": finding.category, "verification": finding.verification_status,
                "confidence": finding.confidence, "snapshot": review.snapshot_id},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": quote(e.location.file_path, safe="/")},
                "region": {"startLine": e.location.start_line, "endLine": e.location.end_line}}} for e in finding.evidence],
        })
    return sarif
