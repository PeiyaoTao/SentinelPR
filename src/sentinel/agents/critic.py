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
        if finding.proof_status == ProofStatus.REPRODUCED_DYNAMICALLY:
            finding.critic_reasoning = "Accepted: Critical/High risk with confirmed dynamic reproduction trace."
        elif finding.proof_status == ProofStatus.STATIC_VERIFIED:
            finding.critic_reasoning = "Accepted: Critical/High risk verified via static AST/pattern analysis."
        elif finding.proof_status in [ProofStatus.EXECUTION_FAILED, ProofStatus.ENV_SETUP_ERROR]:
            finding.critic_reasoning = "Accepted: High risk evaluated under static proof standards (dynamic sandbox execution failed)."
        elif finding.proof_status == ProofStatus.SANDBOX_UNAVAILABLE:
            finding.critic_reasoning = "Accepted: High risk evaluated under static proof standards (container sandbox unavailable)."
        else:
            finding.critic_reasoning = "Accepted: High risk finding accepted under static proof standards."
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
    elif finding.proof_status in [ProofStatus.EXECUTION_FAILED, ProofStatus.ENV_SETUP_ERROR, ProofStatus.SANDBOX_UNAVAILABLE]:
        finding.critic_decision = CriticDecision.REJECT
        finding.critic_reasoning = f"Rejected: Inconclusive dynamic proof for medium/low candidate ({finding.proof_status.value})."
        return finding

    finding.critic_decision = CriticDecision.ACCEPT
    finding.critic_reasoning = "Accepted: Finding verified."
    return finding


import json
import re
from typing import Any, Dict, List, Optional, Tuple

from sentinel.config import default_config
from sentinel.llm import get_llm_client


def consult_llm_critic(finding: Finding, state: PRReviewState) -> Optional[Tuple[CriticDecision, str]]:
    """
    Consults the configured LLM (e.g. local Ollama or cloud model) as adversarial defense counsel.
    Returns (decision, reasoning) or None if LLM call is unavailable or fails.
    """
    if default_config.provider == "heuristics":
        return None

    client = get_llm_client(tier="frontier")
    file_code = state.get("head_files", {}).get(finding.file_path, "")

    prompt = f"""You are the Adversarial Critic Gate for an autonomous code review system.
Your role is to act as defense counsel for the PR author, rigorously filtering out false positives, nitpicks, and incorrect accusations.

Candidate Finding to Review:
- File: {finding.file_path} (Lines {finding.start_line}-{finding.end_line})
- Category: {finding.category.value}
- Severity: {finding.severity.value}
- Title: {finding.title}
- Explanation: {finding.explanation}
- Trust Zone: {finding.trust_zone.value}

Relevant Source Code:
```python
{file_code}
```

Instructions:
1. If this finding points out a genuine defect, concurrency bug, security issue, or fail-fast anti-bloat violation, output decision "ACCEPT".
2. If this finding is a false alarm, harmless code, or an invalid accusation, output decision "REJECT" with your justification.
3. Respond in valid JSON with format:
{{"decision": "ACCEPT" or "REJECT", "reason": "brief explanation"}}
"""

    try:
        raw = client.complete([{"role": "user", "content": prompt}], json_mode=True)
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            decision_str = data.get("decision", "").upper()
            reason = data.get("reason", "LLM review completed.")
            if decision_str == "ACCEPT":
                return CriticDecision.ACCEPT, f"Accepted by LLM Critic: {reason}"
            elif decision_str == "REJECT":
                return CriticDecision.REJECT, f"Rejected by LLM Critic: {reason}"
    except (json.JSONDecodeError, KeyError, ValueError, RuntimeError) as e:
        sys.stderr.write(f"Warning: Critic LLM evaluation failed: {e}\n")
        return None

    return None


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

        # Consult LLM Critic if an LLM provider is active
        if default_config.provider != "heuristics":
            llm_result = consult_llm_critic(evaluated_finding, state)
            if llm_result is not None:
                evaluated_finding.critic_decision, evaluated_finding.critic_reasoning = llm_result

        if evaluated_finding.critic_decision in [CriticDecision.ACCEPT, CriticDecision.DOWNGRADE]:
            verified_findings.append(evaluated_finding)
            seen_keys.add(dedup_key)

    return {"verified_findings": verified_findings}
