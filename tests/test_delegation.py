"""Delegated opinions cannot manufacture evidence, stale citations or gate changes."""
import pytest
from sentinel.config import default_config
from sentinel.delegate import prepare, import_response, package_id
from sentinel.delegation_models import DelegatedReview


@pytest.fixture
def packet(tmp_path, monkeypatch):
    monkeypatch.setattr(default_config, "provider", "deepseek")
    monkeypatch.setattr("sentinel.llm.LLMClient.complete", lambda *a, **k: pytest.fail("Delegation used a model API"))
    (tmp_path / "core.py").write_text("def add(a, b):\n    return a + b\n")
    return tmp_path, prepare(tmp_path)


def answer(package):
    excerpt = package.excerpts[0]
    return DelegatedReview(package_id=package.package_id, reviewer="host-agent", reviewed_excerpts=[excerpt.id],
        findings=[dict(title="Review addition contract", category="logic", priority="high", claim="The expected input contract needs confirmation.",
                       recommendation="Confirm expected types with callers.", evidence=[dict(excerpt_id=excerpt.id, line=excerpt.start_line)])],
        limitations=["Only the supplied excerpt was reviewed."])


def test_roundtrip_keeps_external_feedback_separate_from_gate(packet):
    root, package = packet
    response = answer(package)
    report = import_response(root, package, response)
    assert report.review_outcome.value == "CLEAN"
    assert report.accepted_findings_count == 0
    assert report.delegated_review == response
    assert "unverified advice" in report.summary_markdown
    assert report.sarif_json["runs"][0]["results"] == []
    assert report.delegation_excerpts[0]["source"]
    assert default_config.provider == "deepseek"


def test_source_change_rejects_stale_response(packet):
    root, package = packet
    (root / "core.py").write_text("def add(a, b): return a - b\n")
    with pytest.raises(ValueError, match="snapshot changed"):
        import_response(root, package, answer(package))


def test_packet_tampering_fails_before_import(packet):
    root, package = packet
    response = answer(package)
    package.excerpts[0].source = "fabricated"
    with pytest.raises(ValueError, match="modified"):
        import_response(root, package, response)
    package.package_id = package_id(package)
    response.package_id = package.package_id
    with pytest.raises(ValueError, match="current source"):
        import_response(root, package, response)


@pytest.mark.parametrize("change", ["line", "unreviewed", "wrong_package"])
def test_invalid_citations_and_identity_rejected(packet, change):
    root, package = packet
    response = answer(package)
    if change == "line": response.findings[0].evidence[0].line = 1000
    if change == "unreviewed": response.reviewed_excerpts = []
    if change == "wrong_package": response.package_id = "other"
    with pytest.raises(ValueError):
        import_response(root, package, response)


def test_external_cannot_supply_proof_or_verdict(packet):
    _, package = packet
    raw = answer(package).model_dump()
    raw["findings"][0]["proof_status"] = "STATIC_VERIFIED"
    with pytest.raises(ValueError):
        DelegatedReview.model_validate(raw)


def test_budgeted_packet_discloses_partial_source(tmp_path):
    for i in range(20):
        (tmp_path / f"module{i}.py").write_text("# " + "source " * 300 + "\ndef run(): return 1\n")
    package = prepare(tmp_path, max_chars=9000)
    assert len(package.model_dump_json()) <= 9000
    assert len(package.excerpts) < len(package.source_hashes)
    assert "Bounded excerpts" in package.limitations[0]
