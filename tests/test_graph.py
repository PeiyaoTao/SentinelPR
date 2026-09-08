"""
Tests for SentinelPR LangGraph end-to-end multi-agent workflow.
"""

from sentinel.graph import review_pr
from sentinel.state import FindingCategory, Severity


def test_full_review_flow_catches_mutable_default(sample_python_diff, sample_head_files):
    """
    End-to-end verification that the LangGraph workflow:
    1. Triages diff and slices AST
    2. Fans out to parallel workers
    3. Accumulates findings via operator.add reducer
    4. Passes through test synthesis and sandbox verification
    5. Clears the adversarial critic gate
    6. Produces valid consolidated report and inline comment
    """
    final_state = review_pr(
        diff=sample_python_diff,
        head_files=sample_head_files,
    )

    assert "verified_findings" in final_state
    verified = final_state["verified_findings"]

    # Must have flagged the mutable default argument
    assert len(verified) >= 1
    mutable_finding = next((f for f in verified if "Mutable Default" in f.title), None)
    assert mutable_finding is not None
    assert mutable_finding.category == FindingCategory.LOGIC
    assert mutable_finding.severity == Severity.HIGH

    # Check report
    report = final_state.get("consolidated_report")
    assert report is not None
    assert report.accepted_findings_count >= 1
    assert len(report.inline_comments) >= 1
    assert report.inline_comments[0]["path"] == "services/user_service.py"
    assert "SentinelPR" in report.summary_markdown
