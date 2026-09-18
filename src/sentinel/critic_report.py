"""Render every critic disposition without turning rejected claims into findings."""
from html import escape
from sentinel.state import CriticAudit


def render_critic_audit(records: list[CriticAudit]) -> str:
    if not records:
        return ""
    lines = ["", "## Critic decision audit", "", "<details>", "<summary>Candidate decisions, reasons, and citations</summary>", ""]
    for entry in records:
        lines += [f"<p><strong>{entry.decision}: {escape(entry.title)}</strong><br>",
                  f"<code>{escape(entry.file_path)}:{entry.line}</code>; rule <code>{escape(entry.rule_id)}</code>; candidate <code>{escape(entry.finding_id)}</code><br>",
                  f"Severity: {entry.original_severity.value} → {entry.final_severity.value}; proof: {entry.proof_status.value}<br>",
                  escape(entry.reason) + "</p>",
                  "<p>Original claim: " + escape(entry.claim) + "</p>",
                  "<p>Deterministic assessment: " + escape(entry.deterministic_reason or entry.reason) + "</p>",
                  f"<p>Model status: {entry.model_status}"]
        if entry.model_reason:
            lines += [f"; model: {escape(entry.model or '')}; opinion: {escape(entry.model_decision or '')}<br>", escape(entry.model_reason)]
        lines += ["</p>"]
        for citation in entry.citations:
            lines += [f"- <code>{escape(citation.file_path)}:{citation.line}</code> (source <code>{citation.source_hash[:12]}</code>)"]
        lines += [""]
    return "\n".join([*lines, "Model opinions and source citations do not establish proof.", "", "</details>", ""])
