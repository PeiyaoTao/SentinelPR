"""
Tests for Adversarial Critic Gate: Severity-tiered burden of proof and false-alarm suppression.
"""

from sentinel.agents.critic import evaluate_candidate_finding
from sentinel.state import (
    CriticDecision,
    Finding,
    FindingCategory,
    ProofStatus,
    Severity,
    TrustZone,
)


def test_critic_accepts_critical_finding():
    finding = Finding(
        id="SEC-001",
        category=FindingCategory.SECURITY,
        severity=Severity.CRITICAL,
        file_path="services/auth.py",
        start_line=20,
        end_line=20,
        title="SQL Injection",
        explanation="Raw SQL query",
        proof_status=ProofStatus.STATIC_VERIFIED,
    )
    result = evaluate_candidate_finding(finding)
    assert result.critic_decision == CriticDecision.ACCEPT


def test_critic_downgrades_test_file_finding():
    finding = Finding(
        id="SEC-002",
        category=FindingCategory.SECURITY,
        severity=Severity.CRITICAL,
        file_path="tests/test_auth_mock.py",
        start_line=10,
        end_line=10,
        title="Hardcoded API Key",
        explanation="Test token in mock fixture",
        proof_status=ProofStatus.STATIC_VERIFIED,
    )
    result = evaluate_candidate_finding(finding)
    assert result.critic_decision == CriticDecision.DOWNGRADE
    assert result.severity == Severity.LOW


def test_critic_rejects_unreproduced_logic_finding():
    finding = Finding(
        id="LOGIC-001",
        category=FindingCategory.LOGIC,
        severity=Severity.HIGH,
        file_path="services/calc.py",
        start_line=15,
        end_line=15,
        title="Off-by-one error",
        explanation="Hypothesized off-by-one",
        proof_status=ProofStatus.NOT_REPRODUCED,
    )
    result = evaluate_candidate_finding(finding)
    assert result.critic_decision == CriticDecision.REJECT


def test_critic_rejects_anti_bloat_at_perimeter():
    finding = Finding(
        id="BLOAT-001",
        category=FindingCategory.ANTI_BLOAT,
        severity=Severity.SUGGESTION,
        file_path="api/v1/users.py",
        start_line=5,
        end_line=5,
        title="Ghost Null-Check",
        explanation="Input validation check",
        trust_zone=TrustZone.PERIMETER,
    )
    result = evaluate_candidate_finding(finding)
    assert result.critic_decision == CriticDecision.REJECT
    assert "PERIMETER boundary" in result.critic_reasoning
