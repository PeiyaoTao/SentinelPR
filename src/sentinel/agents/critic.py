"""
Adversarial Critic Gate: Eliminates false positives with a severity-tiered burden of proof.
"""

from typing import Any, Dict, List

from sentinel.state import (
    CriticDecision,
    Finding,
    FindingCategory,
    PRReviewState,
    ProofStatus,
    Severity,
    TrustZone,
)


def evaluate_candidate_finding(finding: Finding) -> Finding:
    """
    Evaluates a candidate finding under the tiered burden of proof.
    Acts as defense counsel for the author to challenge weak accusations.
    """
    # Rule 1: CRITICAL & HIGH Security/Logic findings
    # Accepted unless demonstrably impossible or in a mock/test file
    if finding.severity in [Severity.CRITICAL, Severity.HIGH]:
        if "test" in finding.file_path.lower() and finding.category == FindingCategory.SECURITY:
            # Secrets in test fixtures or mock directories are typically acceptable test data
            finding.critic_decision = CriticDecision.DOWNGRADE
            finding.severity = Severity.LOW
            finding.critic_reasoning = "Downgraded: Finding is located in a test or mock file."
            return finding

        if finding.category == FindingCategory.LOGIC and finding.proof_status == ProofStatus.NOT_REPRODUCED:
            # If dynamic test explicitly passed (hypothesis disproved), reject
            finding.critic_decision = CriticDecision.REJECT
            finding.critic_reasoning = "Rejected: Dynamic reproduction test passed without reproducing defect."
            return finding

        finding.critic_decision = CriticDecision.ACCEPT
        finding.critic_reasoning = "Accepted: Critical/High risk with verified static or dynamic trace."
        return finding

    # Rule 2: ANTI_BLOAT evaluation
    if finding.category == FindingCategory.ANTI_BLOAT:
        if finding.trust_zone == TrustZone.PERIMETER:
            finding.critic_decision = CriticDecision.REJECT
            finding.critic_reasoning = (
                "Rejected: Defensive check is located at the untrusted PERIMETER boundary. "
                "Perimeter validation is mandatory according to the SentinelPR Constitution."
            )
            return finding

        finding.critic_decision = CriticDecision.ACCEPT
        finding.critic_reasoning = (
            "Accepted: Overprotective defensive pattern located in INTERNAL_CORE domain logic, "
            "violating the Fail-Fast Principle."
        )
        return finding

    # Rule 3: MEDIUM and LOW logic findings require dynamic or static proof
    if finding.proof_status == ProofStatus.NOT_REPRODUCED:
        finding.critic_decision = CriticDecision.REJECT
        finding.critic_reasoning = "Rejected: Finding could not be reproduced in sandbox execution."
        return finding

    finding.critic_decision = CriticDecision.ACCEPT
    finding.critic_reasoning = "Accepted: Finding verified."
    return finding


def critic_agent_node(state: PRReviewState) -> Dict[str, Any]:
    """
    LangGraph node: Audits all candidate findings in a single batched pass.
    Deduplicates overlapping findings and filters accepted findings into verified_findings.
    """
    candidate_findings = state.get("candidate_findings", [])
    verified_findings: List[Finding] = []
    seen_keys = set()

    for finding in candidate_findings:
        dedup_key = (finding.file_path, finding.start_line, finding.category)
        if dedup_key in seen_keys:
            continue

        evaluated_finding = evaluate_candidate_finding(finding)
        if evaluated_finding.critic_decision in [CriticDecision.ACCEPT, CriticDecision.DOWNGRADE]:
            verified_findings.append(evaluated_finding)
            seen_keys.add(dedup_key)

    return {"verified_findings": verified_findings}
