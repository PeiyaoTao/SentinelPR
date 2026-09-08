"""
Tests for SentinelPR state models, Pydantic schemas, and reducers.
"""

import operator
from sentinel.state import (
    CriticDecision,
    Finding,
    FindingCategory,
    ProofStatus,
    Severity,
    TrustZone,
)


def test_finding_creation_and_defaults():
    finding = Finding(
        id="TEST-001",
        category=FindingCategory.LOGIC,
        severity=Severity.HIGH,
        file_path="services/test.py",
        start_line=10,
        end_line=12,
        title="Test Logic Defect",
        explanation="Explanation of bug",
        trust_zone=TrustZone.INTERNAL_CORE,
    )

    assert finding.id == "TEST-001"
    assert finding.category == FindingCategory.LOGIC
    assert finding.severity == Severity.HIGH
    assert finding.proof_status == ProofStatus.UNTESTED
    assert finding.critic_decision == CriticDecision.ACCEPT
    assert finding.critic_reasoning is None


def test_state_reducer_list_concatenation():
    """Verifies that operator.add safely merges candidate findings from parallel workers."""
    list_a = [
        Finding(
            id="LOGIC-1",
            category=FindingCategory.LOGIC,
            severity=Severity.HIGH,
            file_path="foo.py",
            start_line=1,
            end_line=2,
            title="Logic bug",
            explanation="...",
        )
    ]
    list_b = [
        Finding(
            id="SEC-1",
            category=FindingCategory.SECURITY,
            severity=Severity.CRITICAL,
            file_path="foo.py",
            start_line=5,
            end_line=6,
            title="Security bug",
            explanation="...",
        )
    ]

    merged = operator.add(list_a, list_b)
    assert len(merged) == 2
    assert merged[0].id == "LOGIC-1"
    assert merged[1].id == "SEC-1"
