"""Rejected and retained decisions must survive graph state and report exports."""
import json
from unittest.mock import Mock
import pytest
from sentinel.agents.critic import critic_agent_node
from sentinel.agents.consolidator import consolidator_agent_node
from sentinel.config import default_config
from sentinel.state import Finding, FindingCategory, Severity, ProofStatus


def candidate(**updates):
    data = dict(id="one", rule_id="example", category=FindingCategory.LOGIC, severity=Severity.HIGH,
                file_path="core.py", start_line=1, end_line=2, title="Suspected behavior", explanation="Original candidate claim")
    return Finding(**{**data, **updates})


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setattr(default_config, "provider", "ollama")
    monkeypatch.setattr(default_config, "llm_critic_enabled", True)
    monkeypatch.setattr(default_config, "llm_critic_max_findings", 8)
    client = Mock(complete=Mock(return_value=json.dumps(dict(decision="REJECT", reason="The supplied function returns a constant.", evidence=[dict(file_path="core.py", line=2)]))))
    monkeypatch.setattr("sentinel.agents.critic.get_llm_client", lambda **kw: client)
    return client


def test_all_discard_paths_have_records_and_report_citations(setup):
    candidates = [candidate(), candidate(id="duplicate"), candidate(id="structural", rule_id="logic.global-mutation")]
    state = {"head_files": {"core.py": "def answer():\n    return 42\n"}, "candidate_findings": candidates}
    result = critic_agent_node(state)
    assert not result["verified_findings"]
    assert [a.decision for a in result["critic_audit"]] == ["REJECT", "DUPLICATE", "REJECT"]
    assert setup.complete.call_count == 1
    record = result["critic_audit"][0]
    assert record.model_reason and record.deterministic_reason
    assert record.claim == "Original candidate claim"
    assert record.citations[0].line == 2 and len(record.citations[0].source_hash) == 64
    report = consolidator_agent_node({**state, **result})["consolidated_report"]
    assert "The supplied function returns a constant" in report.summary_markdown
    assert "core.py:2" in report.summary_markdown
    assert '"model_decision":"REJECT"' in report.model_dump_json()
    assert report.sarif_json["runs"][0]["results"] == []


def test_model_rejection_of_proven_blocker_records_disagreement():
    result = critic_agent_node({"head_files": {"core.py": "def answer():\n    return 42\n"},
                               "candidate_findings": [candidate(proof_status=ProofStatus.STATIC_VERIFIED)]})
    record = result["critic_audit"][0]
    assert record.decision == "ACCEPT" and record.model_decision == "REJECT"
    assert result["verified_findings"][0].severity == Severity.HIGH
    assert "independent adjudication" in " ".join(result["critic_limitations"])


def test_error_and_budget_retention_are_auditable(setup, monkeypatch):
    setup.complete.side_effect = RuntimeError("private token")
    monkeypatch.setattr(default_config, "llm_critic_max_findings", 1)
    result = critic_agent_node({"head_files": {"core.py": "def answer():\n    return 42\n"},
                               "candidate_findings": [candidate(), candidate(id="two", rule_id="second")]})
    assert [a.model_status for a in result["critic_audit"]] == ["unavailable", "budget_exhausted"]
    assert all(a.decision == "DOWNGRADE" for a in result["critic_audit"])
    assert "private token" not in "".join(a.model_dump_json() for a in result["critic_audit"])
