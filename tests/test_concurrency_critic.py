"""Structural validation and model opinions cannot manufacture concurrency proof."""
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from sentinel.agents.critic import critic_agent_node, evaluate_candidate_finding
from sentinel.agents.logic import analyze_symbol_logic
from sentinel.agents.project import repository_critic_node
from sentinel.config import default_config
from sentinel.graph import review_repository
from sentinel.repository import repository_symbols
from sentinel.state import CriticDecision, Finding, FindingCategory, ProofStatus, ReviewOutcome, Severity, TrustZone

SOURCE = "counter = 0\ndef tick():\n    global counter\n    counter += 1\n"


def candidates(source=SOURCE, path="core.py"):
    return [f for symbol in repository_symbols(path, source) for f in analyze_symbol_logic(symbol) if f.rule_id == "logic.global-mutation"]


def state(source=SOURCE):
    return {"candidate_findings": candidates(source), "head_files": {"core.py": source}}


@pytest.fixture(autouse=True)
def config(monkeypatch):
    monkeypatch.setattr(default_config, "provider", "heuristics")
    monkeypatch.setattr(default_config, "llm_critic_enabled", True)
    monkeypatch.setattr(default_config, "llm_critic_max_findings", 8)


def model(monkeypatch, decision="ACCEPT", line=4):
    monkeypatch.setattr(default_config, "provider", "ollama")
    client = Mock()
    client.complete.return_value = json.dumps({"decision": decision, "reason": "Contextual opinion", "evidence": [{"file_path": "core.py", "line": line}]})
    monkeypatch.setattr("sentinel.agents.critic.get_llm_client", lambda **kwargs: client)
    return client


def test_detector_does_not_flag_its_own_source():
    path = Path(__file__).parents[1] / "src/sentinel/agents/logic.py"
    assert candidates(path.read_text(encoding="utf-8"), "logic.py") == []


@pytest.mark.parametrize("source", [
    'def example():\n    text = "global counter += 1"\n',
    'def example():\n    # global counter += 1\n    return 1\n',
    'def example():\n    global counter\n    local = 0\n    local += 1\n',
    'def outer():\n    global counter\n    def inner():\n        counter = 0\n        counter += 1\n',
    'def outer():\n    counter = 0\n    def inner():\n        global counter\n    counter += 1\n',
])
def test_strings_comments_and_other_scopes_are_not_global_mutation(source):
    assert candidates(source) == []


def test_real_mutation_has_exact_location_and_remains_advisory():
    inputs = state()
    found = critic_agent_node(inputs)["verified_findings"]
    assert len(found) == 1
    assert found[0].start_line == 4
    assert found[0].severity == Severity.MEDIUM
    assert found[0].hypothesis
    assert found[0].proof_status == ProofStatus.UNTESTED
    assert inputs["candidate_findings"][0].severity == Severity.HIGH  # no mutation of reducer input


def test_locked_mutation_is_not_called_a_proven_race():
    source = "def tick():\n    global counter\n    with lock:\n        counter += 1\n"
    result = critic_agent_node(state(source))["verified_findings"][0]
    assert result.hypothesis
    assert result.severity == Severity.MEDIUM
    assert "not a demonstrated race" in result.explanation


@pytest.mark.parametrize("proof", [ProofStatus.UNTESTED, ProofStatus.SANDBOX_UNAVAILABLE, ProofStatus.EXECUTION_FAILED, ProofStatus.TIMEOUT])
def test_high_impact_without_proof_does_not_block(proof):
    finding = candidates()[0].model_copy(update={"rule_id": None, "hypothesis": False, "proof_status": proof, "severity": Severity.CRITICAL})
    evaluated = evaluate_candidate_finding(finding)
    assert evaluated.severity == Severity.MEDIUM
    assert evaluated.hypothesis


@pytest.mark.parametrize("node", [critic_agent_node, repository_critic_node])
def test_model_accept_cannot_promote_concurrency_hypothesis(monkeypatch, node):
    client = model(monkeypatch)
    result = node(state())
    finding = result["verified_findings"][0]
    assert finding.severity == Severity.MEDIUM
    assert finding.proof_status == ProofStatus.UNTESTED
    assert finding.hypothesis
    assert client.complete.call_count == 1


def test_no_model_call_for_structurally_invalid_candidate(monkeypatch):
    client = model(monkeypatch)
    inputs = state()
    inputs["head_files"]["core.py"] = 'text = "global counter += 1"\n'
    assert critic_agent_node(inputs)["verified_findings"] == []
    client.complete.assert_not_called()


def test_model_cannot_override_perimeter_rejection(monkeypatch):
    client = model(monkeypatch)
    finding = candidates()[0].model_copy(update={"rule_id": None, "category": FindingCategory.ANTI_BLOAT, "trust_zone": TrustZone.PERIMETER})
    assert critic_agent_node({"candidate_findings": [finding], "head_files": {"core.py": SOURCE}})["verified_findings"] == []
    client.complete.assert_not_called()


def test_model_can_reject_advisory_with_cited_context(monkeypatch):
    model(monkeypatch, "REJECT")
    assert repository_critic_node(state())["verified_findings"] == []


def test_proven_finding_needs_independent_adjudication_of_model_rejection(monkeypatch):
    model(monkeypatch, "REJECT")
    inputs = state()
    inputs["candidate_findings"][0].proof_status = ProofStatus.REPRODUCED_DYNAMICALLY
    result = critic_agent_node(inputs)
    assert result["verified_findings"][0].severity == Severity.HIGH
    assert not result["verified_findings"][0].hypothesis
    assert any("independent adjudication" in note for note in result["critic_limitations"])


@pytest.mark.parametrize("response", ["not JSON", "{}", '{"decision":"ACCEPT","reason":"yes","evidence":[]}', '{"decision":"ACCEPT","reason":"yes","evidence":[{"file_path":"absent.py","line":1}]}', '{"decision":"ACCEPT","reason":"yes","evidence":[{"file_path":"core.py","line":999}]}'])
def test_invalid_model_output_preserves_evidence_gate(monkeypatch, response):
    client = model(monkeypatch)
    client.complete.return_value = response
    result = critic_agent_node(state())
    assert result["verified_findings"][0].severity == Severity.MEDIUM
    assert any("invalid response" in note for note in result["critic_limitations"])


def test_provider_error_is_disclosed_without_exposing_exception_body(monkeypatch):
    client = model(monkeypatch)
    client.complete.side_effect = RuntimeError("private provider detail")
    result = critic_agent_node(state())
    assert result["verified_findings"][0].hypothesis
    assert "private provider detail" not in str(result["critic_limitations"])
    assert any("RuntimeError" in note for note in result["critic_limitations"])


def test_opt_out_and_budget(monkeypatch):
    client = model(monkeypatch)
    monkeypatch.setattr(default_config, "llm_critic_enabled", False)
    critic_agent_node(state())
    client.complete.assert_not_called()
    monkeypatch.setattr(default_config, "llm_critic_enabled", True)
    monkeypatch.setattr(default_config, "llm_critic_max_findings", 1)
    inputs = state()
    inputs["candidate_findings"].append(inputs["candidate_findings"][0].model_copy(update={"rule_id": "another-rule"}))
    result = critic_agent_node(inputs)
    assert client.complete.call_count == 1
    assert len(result["verified_findings"]) == 2
    assert any("budget exhausted" in note for note in result["critic_limitations"])


def test_context_includes_callers_and_stays_bounded(monkeypatch):
    client = model(monkeypatch)
    monkeypatch.setattr(default_config, "llm_critic_context_chars", 1000)
    inputs = state()
    inputs["head_files"]["caller.py"] = "from core import tick\ndef run():\n    tick()\n"
    result = critic_agent_node(inputs)
    payload = json.loads(client.complete.call_args.args[0][1]["content"])
    assert len(json.dumps(payload["excerpts"])) <= 1000
    assert {e["file_path"] for e in payload["excerpts"]} == {"core.py", "caller.py"}
    assert "quality_index" in result


def test_repository_graph_uses_shared_critic_and_reports_limits(tmp_path, monkeypatch):
    (tmp_path / "core.py").write_text(SOURCE)
    model(monkeypatch)
    project_client = Mock()
    project_client.complete.return_value = '{"summary":"Example project","advice":[]}'
    monkeypatch.setattr("sentinel.agents.project.get_llm_client", lambda **kwargs: project_client)
    report = review_repository(tmp_path)["consolidated_report"]
    assert report.review_outcome == ReviewOutcome.CLEAN
    assert "Advisory hypothesis" in report.summary_markdown
    assert "Optional LLM critic: 1 call" in report.summary_markdown
    assert report.critic_limitations
    assert report.sarif_json["runs"][0]["results"][0]["properties"]["hypothesis"]


@pytest.mark.parametrize("value,expected", [("true", True), ("false", False), ("FALSE", False)])
def test_critic_environment_switch(monkeypatch, value, expected):
    from sentinel.config import load_config_from_env
    monkeypatch.setenv("SENTINEL_LLM_CRITIC", value)
    assert load_config_from_env().llm_critic_enabled is expected


def test_invalid_critic_environment_fails_explicitly(monkeypatch):
    from sentinel.config import load_config_from_env
    monkeypatch.setenv("SENTINEL_LLM_CRITIC", "perhaps")
    with pytest.raises(ValueError, match="true or false"):
        load_config_from_env()


def test_repository_self_review_has_no_false_concurrency_blocker(monkeypatch, tmp_path):
    monkeypatch.setattr(default_config, "provider", "heuristics")
    source = Path(__file__).parents[1] / "src/sentinel/agents/logic.py"
    (tmp_path / "logic.py").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    result = review_repository(tmp_path)
    assert not any(f.rule_id == "logic.global-mutation" for f in result["verified_findings"])
    assert result["consolidated_report"].review_outcome == ReviewOutcome.CLEAN
