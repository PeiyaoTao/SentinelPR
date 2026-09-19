"""Metric correctness and offline end-to-end behavior, including honest misses."""
from sentinel.config import default_config
from sentinel.harness.behavior_cases import CASES
from sentinel.harness.behavior_eval import evaluate, metrics, score


def test_duplicate_predictions_are_not_multiple_true_positives():
    label = {"title": "bug", "path": "core.py", "line": 2, "lane": "defect_leads"}
    scored = score([label], [dict(label), dict(label)])
    result = metrics([{"expected": [label], "predictions": [label, label], "score": scored}], "defect_leads")
    assert result["true_positives"] == 1 and result["false_positives"] == 1
    assert result["precision"] == .5 and result["recall"] == 1


def test_undefined_metrics_are_not_reported_as_perfect():
    result = metrics([], "defect_leads")
    assert result["precision"] is None and result["recall"] is None


def test_offline_benchmark_records_known_gap_without_model_or_execution(monkeypatch):
    monkeypatch.setattr(default_config, "provider", "deepseek")
    monkeypatch.setattr("sentinel.llm.LLMClient.complete", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Unexpected LLM call")))
    monkeypatch.setattr("sentinel.harness.sandbox.execute_test_script", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Unexpected target execution")))
    cases = [c for c in CASES if c["id"] in {"off_by_one_known_gap", "correct_last_element"}]
    result = evaluate(cases)
    assert result["metrics"]["defect_leads"]["false_negatives"] == 1
    assert result["model_usage"]["requests"] == 0
    assert result["implementation_hash"] and result["dataset_hash"]
    assert "api_key" not in result["config"]
    assert default_config.provider == "deepseek"



def test_comparison_rejects_different_labels_and_discloses_settings():
    import pytest
    from sentinel.harness.behavior_eval import compare
    baseline = {"dataset_hash": "same", "config": {"provider": "heuristics"}, "mode": "offline", "implementation_hash": "a", "metrics": {"defect_leads": {"true_positives": 2, "false_positives": 1, "false_negatives": 1, "precision": 2/3, "recall": 2/3, "f1": 2/3}}}
    current = {**baseline, "config": {"provider": "model"}, "mode": "live"}
    assert compare(baseline, current)["same_settings"] is False
    with pytest.raises(ValueError):
        compare(baseline, {**current, "dataset_hash": "changed"})



def test_blocking_finding_does_not_hide_incomplete_benchmark_coverage():
    from sentinel.harness.behavior_eval import has_gaps
    from sentinel.state import ConsolidatedReport, ReviewOutcome
    report = ConsolidatedReport(summary_markdown="", review_outcome=ReviewOutcome.CHANGES_REQUIRED,
                                llm_usage=[{"status": "timeout"}])
    assert has_gaps(report)
