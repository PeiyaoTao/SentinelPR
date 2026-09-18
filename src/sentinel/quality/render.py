"""Quality advice in Markdown and SARIF, separate from blocking code verdicts."""


from urllib.parse import quote

from sentinel.quality.models import QualityFinding


METRIC_RULES = {"maintainability.branch-complexity", "readability.deep-nesting", "readability.long-function"}


def group_observations(findings: list[QualityFinding]) -> list[list[QualityFinding]]:
    """Group same-symbol metrics for presentation; preserve every source finding."""
    groups: dict[tuple, list[QualityFinding]] = {}
    for finding in findings:
        anchors = tuple((e.location.file_path, e.location.start_line, e.location.end_line, e.source_hash) for e in finding.evidence)
        key = (finding.subject, anchors) if finding.rule_id in METRIC_RULES else (finding.fingerprint,)
        groups.setdefault(key, []).append(finding)
    priority = {"high": 0, "medium": 1, "low": 2}
    for group in groups.values():
        group.sort(key=lambda f: (priority[f.priority], f.rule_id))
    return sorted(groups.values(), key=lambda group: (
        priority[group[0].priority], not any(f.lifecycle == "new" for f in group),
        -len(group), group[0].subject, group[0].fingerprint,
    ))


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
        lines += ["### Suggested starting points", "",
                  "Ranked by priority, new observations, and overlapping signals. Metrics are review prompts, not proof of defects.", ""]
        for group in groups[:3]:
            first = group[0]
            location = first.evidence[0].location
            lines += [f"- **{first.subject}** (`{location.file_path}:{location.start_line}`): "
                      + "; ".join(f.title for f in group) + ". "
                      + " ".join(dict.fromkeys(f.recommendation for f in group))]
        lines += ["", "<details>", "<summary>Full advisory inventory and evidence</summary>", ""]
        for group in groups:
            lines += [f"### [{group[0].priority}] {group[0].subject}", ""]
            for finding in group:
                lines += [f"**{finding.title}**", "",
                    f"**Rule:** `{finding.rule_id}` | **Verification:** {finding.verification_status} | **Confidence:** {finding.confidence} | **Status:** {finding.lifecycle}", "",
                    finding.explanation, "", f"**Conditions:** {finding.trigger_conditions}", "",
                    "**Evidence:**"]
                lines += [f"- `{e.location.file_path}:{e.location.start_line}-{e.location.end_line}` ({e.kind}; source `{e.source_hash[:12]}`)" for e in finding.evidence]
                lines += [""]
            lines += ["**Advice:** " + " ".join(dict.fromkeys(f.recommendation for f in group)), ""]
        lines += ["</details>", ""]
    lines += ["Unresolved calls describe analyzer limitations; their count is not a defect count.", ""]
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
