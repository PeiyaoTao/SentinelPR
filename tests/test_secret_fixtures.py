"""Synthetic source is auditable; test files cannot hide credential assignments."""
import pytest
from sentinel.agents.security import analyze_symbol_security
from sentinel.agents.critic import critic_agent_node
from sentinel.config import default_config
from sentinel.state import ASTSymbolScope, Severity


def review(source, monkeypatch, path="tests/test_example.py"):
    monkeypatch.setattr(default_config, "provider", "heuristics")
    symbol = ASTSymbolScope(symbol_name="module", symbol_type="module", file_path=path,
                            start_line=1, end_line=len(source.splitlines()), code_snippet=source)
    candidates = analyze_symbol_security(symbol)
    return critic_agent_node({"candidate_findings": candidates, "head_files": {path: source}})


def test_embedded_dummy_rejected_before_model_with_audit(monkeypatch):
    embedded = "api_key = 'abcdefghijklmnop1234'\n"
    source = f"def test_scan(tmp_path):\n    write(tmp_path, 'core.py', {embedded!r})\n"
    result = review(source, monkeypatch)
    assert result["verified_findings"] == []
    audit, = result["critic_audit"]
    assert audit.decision == audit.deterministic_decision == "REJECT"
    assert "synthetic test source" in audit.reason
    assert audit.model_status == "not_requested"


@pytest.mark.parametrize("source", [
    "api_key = 'aDifferentCredential123456'\n",
    "value = 'AKIA' + 'ignored'\naws_key = '" + "AKIA" + "A" * 16 + "'\n",
    "write(path, 'core.py', \"api_key = 'aDifferentCredential123456'\\n\")\n",
    "write(path, 'core.py', \"api_key = 'abcdefghijklmnop1234'\\n\"); api_key = 'aDifferentCredential123456'\n",
])
def test_credentials_in_tests_remain_candidates(source, monkeypatch):
    result = review(source, monkeypatch)
    assert result["verified_findings"]
    assert any(f.severity == Severity.CRITICAL for f in result["verified_findings"])


def test_provider_key_inside_source_fixture_is_retained(monkeypatch):
    embedded = "api_key = '" + "AKIA" + "A" * 16 + "'\n"
    result = review(f"write(path, 'core.py', {embedded!r})\n", monkeypatch)
    assert any(f.title == "Hardcoded AWS Access Key" for f in result["verified_findings"])


def test_fixture_does_not_hide_later_actual_secret(monkeypatch):
    embedded = "api_key = 'abcdefghijklmnop1234'\n"
    result = review(f"write(path, 'core.py', {embedded!r})\napi_key = 'aDifferentCredential123456'\n", monkeypatch)
    assert len(result["verified_findings"]) == 1
    assert result["verified_findings"][0].start_line == 2


@pytest.mark.parametrize("value", ["abcdefghijklmnop1234", "exampleCredentialValue12345"])
def test_embedded_benchmark_placeholder_outside_tests(monkeypatch, value):
    embedded = f"api_key = {value!r}\n"
    source = f"CASES = [{{'files': {{'core.py': {embedded!r}}}}}]\n"
    result = review(source, monkeypatch, "src/benchmarks/cases.py")
    assert result["verified_findings"] == []
    assert result["critic_audit"][0].deterministic_decision == "REJECT"
    actual = review(embedded, monkeypatch)
    assert actual["verified_findings"][0].severity == Severity.CRITICAL


def test_actual_benchmark_file_through_pr_triage(monkeypatch):
    from pathlib import Path
    from sentinel.agents.triage import slice_ast_symbols
    monkeypatch.setattr(default_config, "provider", "heuristics")
    path = "src/sentinel/harness/behavior_cases.py"
    source = Path(path).read_text(encoding="utf-8")
    symbols = slice_ast_symbols(path, source, set(range(14, len(source.splitlines()) + 1)))
    candidates = [f for symbol in symbols for f in analyze_symbol_security(symbol)]
    assert len(candidates) == 2
    lines = source.splitlines()
    assert all("api_key =" in lines[f.start_line - 1] for f in candidates)
    result = critic_agent_node({"candidate_findings": candidates, "head_files": {path: source}})
    assert result["verified_findings"] == []
    assert all(a.deterministic_decision == "REJECT" for a in result["critic_audit"])


@pytest.mark.parametrize("value", ["aDifferentCredential123456", "AKIA" + "A" * 16])
def test_benchmark_does_not_hide_unknown_or_provider_keys(monkeypatch, value):
    source = f"CASES = [{('api_key = ' + repr(value))!r}]\n"
    assert review(source, monkeypatch, "src/benchmarks/cases.py")["verified_findings"]


def test_same_line_unknown_embedded_source_is_not_hidden(monkeypatch):
    dummy = "api_key = 'abcdefghijklmnop1234'"
    unknown = "api_key = 'aDifferentCredential123456'"
    source = f"CASES = [{dummy!r}, {unknown!r}]\n"
    assert review(source, monkeypatch, "src/benchmarks/cases.py")["verified_findings"]
