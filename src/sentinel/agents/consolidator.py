"""
Consolidator Agent: Validates diff-hunk line offsets (preventing GitHub 422 errors)
and generates GitHub PR comments and standard SARIF 2.1.0 output.
"""

from sentinel.quality.render import render_quality, append_quality_sarif

import ast
import json
from typing import Any, Dict, List, Set

from sentinel.state import (
    ConsolidatedReport,
    DiffHunk,
    Finding,
    PRReviewState,
    ReviewOutcome,
    Severity,
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
        rule_id = finding.rule_id or finding.category.value
        if rule_id not in seen_rules:
            seen_rules.add(rule_id)
            rules.append({
                "id": rule_id,
                "name": finding.category.value,
                "shortDescription": {"text": finding.title},
            })

        sarif_level = "error" if finding.severity.value in ["CRITICAL", "HIGH"] else "warning"
        if finding.hypothesis or finding.severity.value in ["LOW", "SUGGESTION"]:
            sarif_level = "note"

        results.append({
            "ruleId": rule_id,
            "level": sarif_level,
            "message": {"text": f"[{finding.title}] {finding.explanation}"},
            "properties": {"hypothesis": finding.hypothesis, "proofStatus": finding.proof_status.value},
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
            f"**Evidence classification**: {'Advisory hypothesis' if finding.hypothesis else finding.proof_status.value}\n\n"
            f"{finding.explanation}\n\n"
        )
        # Structured Suggestions: Only emit ```suggestion when exact replacement produces valid syntax
        if finding.exact_replacement:
            target_content = state.get("head_files", {}).get(finding.file_path, "")
            is_valid_replacement = False
            if target_content:
                lines = target_content.splitlines()
                repl = finding.exact_replacement
                start_idx = max(0, repl.start_line - 1)
                end_idx = min(len(lines), repl.end_line)
                candidate_lines = lines[:start_idx] + repl.replacement_text.splitlines() + lines[end_idx:]
                try:
                    ast.parse("\n".join(candidate_lines))
                    is_valid_replacement = True
                except SyntaxError:
                    is_valid_replacement = False
            else:
                try:
                    ast.parse(finding.exact_replacement.replacement_text)
                    is_valid_replacement = True
                except SyntaxError:
                    is_valid_replacement = False

            if is_valid_replacement:
                comment_body += f"```suggestion\n{finding.exact_replacement.replacement_text}\n```\n\n"
            else:
                guidance = finding.remediation_guidance or finding.suggested_fix or finding.exact_replacement.replacement_text
                comment_body += f"**Suggested Fix**:\n{guidance}\n\n"
        elif finding.remediation_guidance or finding.suggested_fix:
            comment_body += f"**Suggested Fix**:\n{finding.remediation_guidance or finding.suggested_fix}\n\n"

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
    risk_assessment = state.get("risk_assessment")

    from sentinel.config import default_config

    engine_name = default_config.provider.capitalize()
    if default_config.fast_model == default_config.frontier_model:
        model_display = f"`{default_config.fast_model}`"
    else:
        model_display = f"Fast: `{default_config.fast_model}` | Frontier: `{default_config.frontier_model}`"
    status_label = "CLEAN" if not verified_findings else f"{accepted_count} Finding(s) Retained"

    summary_lines = [
        "## SentinelPR Quality Gate Report",
        f"**Engine**: {engine_name} ({model_display}) | **Evaluated**: {total_candidates} candidate findings | **Status**: {status_label}\n",
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

    if risk_assessment:
        summary_lines.append("### PR Review Effort & Blast Radius")
        summary_lines.append(f"- **Review effort**: `{risk_assessment.risk_level.value}`")
        summary_lines.append(f"- **Changed-scope complexity sum**: `{risk_assessment.cyclomatic_complexity}` (sum of scope scores; nested scopes may overlap)")
        summary_lines.append(f"- **Total Churn**: `{risk_assessment.total_churn_lines}` lines")
        summary_lines.append(f"- **Perimeter Exposed**: `{risk_assessment.perimeter_symbols_count}` public symbols")
        summary_lines.append(f"- **Test files changed**: `{'Yes' if risk_assessment.has_test_coverage else 'No'}`\n")

    uninspected_files = state.get("uninspected_files", [])
    risk_indicators = state.get("risk_indicators", [])

    has_blocking = any(f.severity in [Severity.CRITICAL, Severity.HIGH] for f in verified_findings)
    if has_blocking:
        review_outcome = ReviewOutcome.CHANGES_REQUIRED
    elif uninspected_files or (state.get("quality_review") and not state["quality_review"].complete):
        review_outcome = ReviewOutcome.INCOMPLETE_REVIEW
    else:
        review_outcome = ReviewOutcome.CLEAN

    summary_lines[1] = (
        f"**Engine**: {engine_name} ({model_display}) | **Evaluated**: {total_candidates} candidate findings | **Status**: {review_outcome.value}\n"
    )
    if uninspected_files:
        summary_lines.append("> [!WARNING]")
        summary_lines.append(f"> **Incomplete Analysis**: {len(uninspected_files)} changed file(s) could not be inspected:")
        for uf in uninspected_files:
            summary_lines.append(f"> - `{uf}`")
        summary_lines.append("")

    if state.get("critic_limitations"):
        summary_lines.extend(["### Critic limitations", "", *(f"- {note}" for note in state["critic_limitations"]), ""])
    summary_markdown = "\n".join(summary_lines) + "\n\n" + render_quality(state.get("quality_review"))
    sarif = append_quality_sarif(generate_sarif(verified_findings), state.get("quality_review"))

    report = ConsolidatedReport(
        critic_limitations=state.get("critic_limitations", []),
        quality_review=state.get("quality_review"),
        summary_markdown=summary_markdown,
        review_outcome=review_outcome,
        inline_comments=inline_comments,
        out_of_hunk_notes=out_of_hunk_notes,
        sarif_json=sarif,
        total_findings_count=total_candidates,
        accepted_findings_count=accepted_count,
        rejected_findings_count=rejected_count,
        risk_assessment=risk_assessment,
        risk_indicators=risk_indicators,
        uninspected_files=uninspected_files,
    )

    from sentinel.checks.report import refresh_executive_summary
    refresh_executive_summary(report)
    return {"consolidated_report": report, "review_outcome": review_outcome}
