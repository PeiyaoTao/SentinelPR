"""Report facts, prioritization and complete evidence exports."""
import pytest
from sentinel.agents.consolidator import consolidator_agent_node, generate_sarif
from sentinel.agents.risk import evaluate_pr_risk
from sentinel.checks.models import CHECK_NAMES, CheckResult, ValidationReport
from sentinel.checks.report import attach_validation, refresh_executive_summary, validation_outcome
from sentinel.config import SentinelConfig, default_config
from sentinel.quality.index import RepositoryIndex
from sentinel.quality.models import QualityReview
from sentinel.quality.pipeline import analyze_quality
from sentinel.quality.render import group_observations, render_quality, append_quality_sarif
from sentinel.state import ConsolidatedReport, ReviewOutcome, RiskLevel


def test_large_change_is_review_effort_not_critical_defect(monkeypatch):
    monkeypatch.setattr(default_config, "provider", "heuristics")
    risk, indicators = evaluate_pr_risk(["tests/test_app.py"], [], 3400)
    assert risk.risk_level == RiskLevel.HIGH
    assert indicators == []
    report = consolidator_agent_node({"risk_assessment": risk})["consolidated_report"]
    assert report.review_outcome == ReviewOutcome.CLEAN
    assert "Complexity Delta" not in report.summary_markdown
    assert "Test Coverage Included" not in report.summary_markdown
    assert "Test files changed" in report.summary_markdown
    assert "Measured test coverage: unavailable" in report.summary_markdown


def test_summary_replaced_after_all_checks_complete():
    report = ConsolidatedReport(summary_markdown="# Review\nStatus: CLEAN")
    refresh_executive_summary(report)
    assert "has not been run" in report.summary_markdown
    validation = ValidationReport(snapshot_id="abc", results=[
        CheckResult(name=name, status="passed", summary="completed") for name in CHECK_NAMES])
    attach_validation(report, validation)
    assert "has not been run" not in report.summary_markdown
    assert report.summary_markdown.count("**Review summary:**") == 1
    for name in CHECK_NAMES:
        assert f"{name}: passed" in report.summary_markdown
    assert "Measured test coverage: unavailable" in report.summary_markdown


@pytest.mark.parametrize("previous", list(ReviewOutcome))
@pytest.mark.parametrize("status", ["passed", "failed", "incomplete", "error"])
def test_outcome_precedence_preserves_existing_verdict(previous, status):
    order = [ReviewOutcome.CLEAN, ReviewOutcome.INCOMPLETE_REVIEW,
             ReviewOutcome.CHANGES_REQUIRED, ReviewOutcome.INFRASTRUCTURE_FAILURE]
    check_outcome = dict(passed=order[0], incomplete=order[1], failed=order[2], error=order[3])[status]
    validation = ValidationReport(snapshot_id="abc", results=[CheckResult(name="tests", status=status, summary="result")])
    assert validation_outcome(previous, validation) == max([previous, check_outcome], key=order.index)


def test_same_symbol_metrics_group_without_losing_sarif_evidence():
    source = "def run(value):\n    if value:\n        if value > 1:\n            return value\n    return 0\n"
    index = RepositoryIndex({f"module{i}.py": source for i in range(4)})
    findings = analyze_quality(index, SentinelConfig(quality_max_complexity=1, quality_max_nesting=1))
    metrics = [f for f in findings if f.rule_id in {"maintainability.branch-complexity", "readability.deep-nesting"}]
    review = QualityReview(snapshot_id="abc", policy_id="test", analyzed_files=[f"module{i}.py" for i in range(4)], specialists=["readability", "maintainability"], findings=metrics)
    groups = group_observations(metrics)
    assert len(groups) == 4
    assert all(len(group) == 2 for group in groups)
    text = render_quality(review)
    top = text.split("### Suggested starting points")[1].split("<details>")[0]
    assert top.count("- **") == 3
    assert "Unresolved calls describe analyzer limitations" in text
    sarif = append_quality_sarif(generate_sarif([]), review)
    assert len(sarif["runs"][0]["results"]) == len(metrics)
    assert {r["partialFingerprints"]["sentinelQuality/v1"] for r in sarif["runs"][0]["results"]} == {f.fingerprint for f in metrics}



def test_github_summary_does_not_duplicate_inventory_or_hide_coverage():
    from sentinel.pr_summary import render_pr_summary
    from sentinel.quality.models import ContextualAdvice
    review = QualityReview(snapshot_id="abc", policy_id="test", analyzed_files=["app.py"], specialists=["maintainability"],
                           contextual_advice=[ContextualAdvice(fingerprints=[str(i)], subject=f"app.f{i}", status="budget_exhausted") for i in range(100)])
    report = ConsolidatedReport(summary_markdown="Very long full evidence. " * 10000,
                                quality_review=review, uninspected_files=["ui.ts"],
                                review_outcome=ReviewOutcome.INCOMPLETE_REVIEW)
    text = render_pr_summary(report, "abcd", "https://github.com/o/r/actions/runs/1")
    assert len(text) < 2000
    assert "0/100" in text and "budget_exhausted: 100" in text
    assert "Uninspected files" in text and "INCOMPLETE_REVIEW" in text
    assert "https://github.com/o/r/actions/runs/1" in text
    assert "Very long full evidence" not in text
    assert len(report.summary_markdown) > 100000
