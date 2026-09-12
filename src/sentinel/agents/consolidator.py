"""
Consolidator Agent: Validates diff-hunk line offsets (preventing GitHub 422 errors)
and generates GitHub PR comments and standard SARIF 2.1.0 output.
"""

from typing import Any, Dict, List, Set
import json

from sentinel.state import (
    ConsolidatedReport,
    DiffHunk,
    Finding,
    PRReviewState,
)


def get_hunk_line_ranges(hunks: List[DiffHunk]) -> Dict[str, Set[int]]:
    """
    Builds a lookup of all modified and context line numbers available in the PR diff hunks.
    """
    hunk_lines: Dict[str, Set[int]] = {}
    for hunk in hunks:
        if hunk.file_path not in hunk_lines:
            hunk_lines[hunk.file_path] = set()

        current_line = hunk.new_start
        for line in hunk.content.splitlines():
            if line.startswith("@@"):
                continue
            elif line.startswith("-"):
                continue
            else:
                # Additions and context lines are valid for GitHub inline comments
                hunk_lines[hunk.file_path].add(current_line)
                current_line += 1

    return hunk_lines


def generate_sarif(verified_findings: List[Finding]) -> Dict[str, Any]:
    """Generates standard SARIF 2.1.0 payload for CI security quality gates."""
    rules = []
    results = []
    seen_rules = set()

    for finding in verified_findings:
        rule_id = finding.category.value
        if rule_id not in seen_rules:
            seen_rules.add(rule_id)
            rules.append({
                "id": rule_id,
                "name": finding.category.value,
                "shortDescription": {"text": finding.title},
            })

        sarif_level = "error" if finding.severity.value in ["CRITICAL", "HIGH"] else "warning"
        if finding.severity.value in ["LOW", "SUGGESTION"]:
            sarif_level = "note"

        results.append({
            "ruleId": rule_id,
            "level": sarif_level,
            "message": {"text": f"[{finding.title}] {finding.explanation}"},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": finding.file_path},
                        "region": {
                            "startLine": finding.start_line,
                            "endLine": finding.end_line,
                        },
                    }
                }
            ],
        })

    return {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "SentinelPR",
                        "semanticVersion": "0.1.0",
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }


def consolidator_agent_node(state: PRReviewState) -> Dict[str, Any]:
    """
    LangGraph node: Ingests verified findings and diff hunks, computes diff offsets,
    and formats GitHub inline comments, summary markdown, and SARIF output.
    """
    verified_findings = state.get("verified_findings", [])
    hunks = state.get("hunks", [])
    candidate_findings = state.get("candidate_findings", [])

    hunk_lines_map = get_hunk_line_ranges(hunks)

    inline_comments: List[Dict[str, Any]] = []
    out_of_hunk_notes: List[Dict[str, Any]] = []

    for finding in verified_findings:
        valid_lines = hunk_lines_map.get(finding.file_path, set())
        # Target end_line for comment anchor
        target_line = finding.end_line

        comment_body = (
            f"### SentinelPR: {finding.title}\n"
            f"**Severity**: `{finding.severity.value}` | **Category**: `{finding.category.value}` | **Zone**: `{finding.trust_zone.value}`\n\n"
            f"{finding.explanation}\n\n"
        )
        if finding.suggested_fix:
            comment_body += f"```suggestion\n{finding.suggested_fix}\n```\n\n"
        if finding.critic_reasoning:
            comment_body += f"> *Critic Gate Verdict: {finding.critic_reasoning}*"

        # Diff Offset Validation (Prevents GitHub 422 Error)
        if target_line in valid_lines:
            inline_comments.append({
                "path": finding.file_path,
                "line": target_line,
                "side": "RIGHT",
                "body": comment_body,
                "finding_id": finding.id,
            })
        else:
            out_of_hunk_notes.append({
                "path": finding.file_path,
                "line": target_line,
                "body": comment_body,
                "finding_id": finding.id,
            })

    # Generate PR Summary Markdown
    accepted_count = len(verified_findings)
    total_candidates = len(candidate_findings)
    rejected_count = total_candidates - accepted_count

    summary_lines = [
        "## SentinelPR Quality Gate Report",
        f"**Summary**: Evaluated {total_candidates} candidate findings. "
        f"**{accepted_count} Accepted**, **{rejected_count} Filtered by Adversarial Critic**.\n",
    ]

    if verified_findings:
        summary_lines.append("| Category | Severity | File | Line | Title |")
        summary_lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for f in verified_findings:
            summary_lines.append(
                f"| `{f.category.value}` | `{f.severity.value}` | `{f.file_path}` | L{f.start_line}-L{f.end_line} | {f.title} |"
            )
        summary_lines.append("")

    if out_of_hunk_notes:
        summary_lines.append("### Context Observations (Outside Diff Hunks)")
        for note in out_of_hunk_notes:
            summary_lines.append(f"- **{note['path']}:{note['line']}**: {note['body'].splitlines()[0]}")
        summary_lines.append("")

    summary_markdown = "\n".join(summary_lines)
    sarif = generate_sarif(verified_findings)

    report = ConsolidatedReport(
        summary_markdown=summary_markdown,
        inline_comments=inline_comments,
        out_of_hunk_notes=out_of_hunk_notes,
        sarif_json=sarif,
        total_findings_count=total_candidates,
        accepted_findings_count=accepted_count,
        rejected_findings_count=rejected_count,
    )

    return {"consolidated_report": report}
