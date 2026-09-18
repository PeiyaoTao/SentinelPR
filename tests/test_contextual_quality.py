"""Contextual advice must stay grounded, bounded, advisory, and auditable."""
import json
from unittest.mock import Mock
import pytest
from sentinel.config import default_config, SentinelConfig, load_config_from_env
from sentinel.quality.contextual import assess_group, build_context, contextual_quality_node, validate_decision
from sentinel.quality.models import ContextualAdvice, QualityReview
from sentinel.quality.pipeline import analyze_quality
from sentinel.quality.index import RepositoryIndex
from sentinel.quality.ranking import group_observations, ranked_recommendations
from sentinel.quality.render import render_quality, append_quality_sarif
from sentinel.agents.consolidator import generate_sarif
from sentinel.harness.quality_eval import CASES, case_input, evaluate


@pytest.fixture(autouse=True)
def config(monkeypatch):
    monkeypatch.setattr(default_config, "provider", "ollama")
    monkeypatch.setattr(default_config, "llm_quality_enabled", True)
    monkeypatch.setattr(default_config, "llm_quality_max_groups", 5)


def response(disposition="recommend", path="subject.py", line=1, **updates):
    data = dict(disposition=disposition, rationale="The charge loop can be exercised without receipt I/O after extraction.",
                recommendation="Extract the charge calculation into a pure function, leaving receipt writing in charge_order." if disposition == "recommend" else "",
                impact="medium", impact_reason="Charge rules currently require receipt I/O to test.",
                benefit="high", benefit_reason="Separating calculation permits direct charge-rule tests.", confidence="high",
                evidence=[dict(file_path=path, line=line)])
    data.update(updates)
    return json.dumps(data)


def test_context_supplies_observed_code_callers_and_tests():
    group, _ = case_input(CASES[2])
    files = {"subject.py": CASES[2]["source"],
             "caller.py": "from subject import charge_order\ndef checkout():\n    return charge_order([], 'receipt')\n",
             "tests/test_charge.py": "from subject import charge_order\ndef test_empty(tmp_path):\n    assert charge_order([], tmp_path / 'receipt') == 0\n"}
    payload, complete = build_context(group, RepositoryIndex(files), 18000)
    assert complete
    assert {e["file_path"] for e in payload["excerpts"]} == set(files)
    assert len(json.dumps(payload)) <= 18000
    assert "Validation" in payload["limitations"]


@pytest.mark.parametrize("disposition", ["recommend", "keep", "inconclusive"])
def test_valid_opinions_do_not_mutate_static_findings(disposition):
    group, index = case_input(CASES[2])
    original = group[0].model_dump()
    item, called = assess_group(group, index, SentinelConfig(), Mock(complete=Mock(return_value=response(disposition))))
    assert called and item.status == "reviewed"
    assert item.decision.disposition == disposition
    assert group[0].model_dump() == original
    assert item.context_hashes["subject.py"] == index.hashes["subject.py"]


@pytest.mark.parametrize("raw", ["{}", "not json", response(path="missing.py"), response(line=999),
    response(recommendation=""), response(impact_reason=" "), response(proof_status="STATIC_VERIFIED"), response("keep", recommendation="Remove validation")])
def test_invalid_advice_never_becomes_a_recommendation(raw):
    group, index = case_input(CASES[2])
    item, called = assess_group(group, index, SentinelConfig(), Mock(complete=Mock(return_value=raw)))
    assert called and item.status == "unavailable"
    assert item.decision is None
    assert not ranked_recommendations([item])


def test_related_citation_alone_cannot_justify_action():
    group, index = case_input(CASES[2])
    payload, _ = build_context(group, index, 18000)
    payload["excerpts"].append(dict(file_path="other.py", start_line=1, end_line=2, source=""))
    with pytest.raises(ValueError, match="observed code"):
        validate_decision(response(path="other.py"), payload, group)


def test_incomplete_primary_context_skips_model():
    group, index = case_input({**CASES[2], "source": "def charge_order():\n    value = '" + "x" * 3000 + "'\n    return value\n"})
    client = Mock()
    item, called = assess_group(group, index, SentinelConfig(llm_quality_context_chars=1000), client)
    assert not called and item.status == "insufficient_context"
    client.complete.assert_not_called()


def test_provider_failure_is_disclosed_without_raw_body():
    group, index = case_input(CASES[2])
    client = Mock(complete=Mock(side_effect=RuntimeError("private credential")))
    item, called = assess_group(group, index, SentinelConfig(), client)
    assert called and item.status == "unavailable"
    assert "RuntimeError" in item.limitation
    assert "private credential" not in item.model_dump_json()


def make_state():
    index = RepositoryIndex({"a.py": CASES[0]["source"], "b.py": CASES[0]["source"]})
    findings = [f for f in analyze_quality(index, SentinelConfig(quality_max_complexity=1)) if f.category == "maintainability"]
    return {"quality_index": index, "quality_review": QualityReview(snapshot_id=index.snapshot_id, policy_id="p",
            analyzed_files=list(index.files), specialists=["maintainability"], findings=findings)}


def test_budget_and_disabled_mode_are_explicit(monkeypatch):
    client = Mock(complete=Mock(return_value=response("keep", path="a.py")))
    monkeypatch.setattr("sentinel.quality.contextual.get_llm_client", lambda **kw: client)
    monkeypatch.setattr(default_config, "llm_quality_max_groups", 1)
    state = make_state()
    review = contextual_quality_node(state)["quality_review"]
    assert client.complete.call_count == 1
    assert [a.status for a in review.contextual_advice] == ["reviewed", "budget_exhausted"]
    assert state["quality_review"].contextual_advice == []
    client.reset_mock()
    monkeypatch.setattr(default_config, "llm_quality_enabled", False)
    review = contextual_quality_node(state)["quality_review"]
    client.complete.assert_not_called()
    assert any("disabled" in s for s in review.limitations)


def test_keep_visible_in_inventory_and_sarif_without_action_item(monkeypatch):
    state = make_state()
    state["quality_review"].findings = group_observations(state["quality_review"].findings)[0]
    client = Mock(complete=Mock(return_value=response("keep", path="a.py")))
    monkeypatch.setattr("sentinel.quality.contextual.get_llm_client", lambda **kw: client)
    review = contextual_quality_node(state)["quality_review"]
    text = render_quality(review)
    assert "Keep this implementation" in text
    assert "No contextual change recommendation established" in text
    assert "Rule prompt" not in text
    sarif = append_quality_sarif(generate_sarif([]), review)
    assert len(sarif["runs"][0]["results"]) == len(review.findings)
    assert sarif["runs"][0]["results"][0]["properties"]["contextualReview"]["decision"]["disposition"] == "keep"
    assert "Rule prompt" not in sarif["runs"][0]["results"][0]["message"]["text"]


def test_ranking_uses_impact_confidence_benefit_with_reasons():
    group, index = case_input(CASES[2])
    payload, _ = build_context(group, index, 18000)
    def entry(name, **kw):
        return ContextualAdvice(fingerprints=[name], subject=name, status="reviewed", decision=validate_decision(response(**kw), payload, group))
    low = entry("a", impact="low")
    strong = entry("z", impact="high")
    uncertain = entry("b", impact="high", confidence="low")
    keep = entry("keep", disposition="keep", impact="high")
    assert ranked_recommendations([low, keep, uncertain, strong]) == [strong, uncertain, low]


@pytest.mark.parametrize("value,expected", [("true", True), ("FALSE", False)])
def test_quality_configuration(monkeypatch, value, expected):
    monkeypatch.setenv("SENTINEL_LLM_QUALITY", value)
    monkeypatch.setenv("SENTINEL_QUALITY_MAX_GROUPS", "2")
    cfg = load_config_from_env()
    assert cfg.llm_quality_enabled is expected and cfg.llm_quality_max_groups == 2


def test_negative_budget_rejected(monkeypatch):
    monkeypatch.setenv("SENTINEL_QUALITY_MAX_GROUPS", "-1")
    with pytest.raises(ValueError):
        load_config_from_env()


def test_replay_evaluation_measures_false_and_missed_recommendations():
    responses = {case["id"]: response(case["expected"]) for case in CASES}
    result = evaluate(SentinelConfig(), responses=responses)
    assert result["metrics"]["matches_reference"] == 4
    responses["necessary_cases"] = response()
    responses["separable_calculation_io"] = response("keep")
    result = evaluate(SentinelConfig(), responses=responses)
    assert result["metrics"]["false_recommendations"] == 1
    assert result["metrics"]["missed_recommendations"] == 1


def test_context_selection_uses_known_relationships_before_alphabetical_order():
    from sentinel.quality.ranking import review_selection
    state = make_state()
    index = RepositoryIndex({**state["quality_index"].files, "use_b.py": "from b import classify\ndef use(): return classify(0)\n"})
    groups = group_observations(state["quality_review"].findings)
    selected = review_selection(groups, index)
    assert selected[0][0][0].subject.startswith("b.py")
    assert "1 known" in selected[0][1]


@pytest.mark.parametrize("mode", ["pr", "repository"])
def test_both_graphs_export_context_and_critic_audit(tmp_path, monkeypatch, mode):
    import difflib
    from sentinel.graph import review_pr, review_repository
    from sentinel.state import ReviewOutcome
    source = "counter = 0\ndef tick():\n    global counter\n    counter += 1\n    if counter > 1:\n        return 1\n    return 0\n"
    (tmp_path / "core.py").write_text(source, encoding="utf-8")
    monkeypatch.setattr(default_config, "quality_max_complexity", 1)
    critic = Mock(complete=Mock(return_value=json.dumps(dict(decision="REJECT", reason="Concurrency is not established by the supplied callers.", evidence=[dict(file_path="core.py", line=4)]))))
    quality = Mock(complete=Mock(return_value=response("keep", path="core.py", line=5)))
    project = Mock(complete=Mock(return_value='{"summary":"Static fixture assessment","advice":[]}'))
    monkeypatch.setattr("sentinel.agents.critic.get_llm_client", lambda **kw: critic)
    monkeypatch.setattr("sentinel.quality.contextual.get_llm_client", lambda **kw: quality)
    monkeypatch.setattr("sentinel.agents.project.get_llm_client", lambda **kw: project)
    def network_forbidden(*args, **kwargs):
        raise AssertionError("Regression fixtures must not make network calls")
    monkeypatch.setattr("requests.sessions.Session.request", network_forbidden)
    if mode == "repository":
        result = review_repository(tmp_path)
    else:
        diff = "diff --git a/core.py b/core.py\n" + "".join(difflib.unified_diff([], source.splitlines(True), fromfile="a/core.py", tofile="b/core.py"))
        result = review_pr(diff, {"core.py": source}, {"core.py": ""})
    report = result["consolidated_report"]
    assert report.review_outcome == ReviewOutcome.CLEAN
    assert report.critic_audit[0].decision == "REJECT"
    assert report.quality_review.contextual_advice[0].decision.disposition == "keep"
    assert "Critic decision audit" in report.summary_markdown
    assert "Keep this implementation" in report.summary_markdown
    assert report.sarif_json["runs"][0]["properties"]["criticAudit"][0]["decision"] == "REJECT"
    if mode == "repository":
        payload = json.loads(project.complete.call_args.args[0][1]["content"])
        assert payload["contextual_quality_decisions"][0]["decision"] == "keep"
