"""Shared quality orchestration, evidence gate, PR scoping and baseline comparison."""

import json
from sentinel.agents.triage import extract_changed_line_numbers, parse_diff_hunks
from sentinel.config import default_config
from sentinel.quality.analyzers import SPECIALISTS
from sentinel.quality.baseline import compare_baseline
from sentinel.quality.index import RepositoryIndex, digest
from sentinel.quality.models import QualityFinding, QualityReview


def verify_evidence(index, finding) -> bool:
    """Reject invalid or stale provenance before anything is rendered or published."""
    for evidence in finding.evidence:
        location = evidence.location
        if evidence.source_hash != index.hashes.get(location.file_path):
            return False
        if not 1 <= location.start_line <= location.end_line <= len(index.files[location.file_path].splitlines()):
            return False
    return True


def analyze_quality(index, config):
    findings = []
    for specialist in SPECIALISTS.values():
        findings.extend(specialist(index, config))
    unique: dict[str, QualityFinding] = {}
    for finding in findings:
        if verify_evidence(index, finding):
            unique.setdefault(finding.fingerprint, finding)
    return sorted(unique.values(), key=lambda f: ({"high": 0, "medium": 1, "low": 2}[f.priority], f.rule_id, f.subject))


def quality_review_node(state):
    index = state.get("quality_index") or RepositoryIndex(state.get("head_files", {}))
    findings = analyze_quality(index, default_config)
    limitations = [
        "Specialists inspect Python statically. Quality observations are advisory, not demonstrated defects.",
        "Import edges cover unconditional module-level imports under repository-root and src layouts; conditional, dynamic and unresolved imports are not complete dependencies.",
        "Call relationships resolve direct local/imported top-level functions only; methods, closures and dynamic dispatch can remain unresolved.",
        "Security paths are local syntactic hypotheses, not whole-program taint or authorization analysis; performance hypotheses require workload evidence.",
        *index.limitations,
    ]
    legacy = {(f.file_path, f.start_line) for f in state.get("verified_findings", []) if f.category.value == "SECURITY"}
    findings = [f for f in findings if not (f.category == "security" and any(
        (e.location.file_path, e.location.start_line) in legacy for e in f.evidence))]
    repository = state.get("repository_inventory")
    if repository is None:
        changed = extract_changed_line_numbers(parse_diff_hunks(state.get("diff", "")))
        findings = [f for f in findings if any(any(
            e.location.start_line <= line <= e.location.end_line for line in changed.get(e.location.file_path, set())) for e in f.evidence)]
        base = RepositoryIndex(state.get("base_files", {}))
        previous = {f.fingerprint for f in analyze_quality(base, default_config)}
        findings = [f for f in findings if f.fingerprint not in previous]
        limitations.append("PR quality checks use only supplied base/head files and changed locations. Missing surrounding modules limit cross-file analysis; absent base files prevent a full regression comparison.")
    capped = len(findings) > default_config.quality_max_findings
    if capped:
        limitations.append(f"Finding budget reached: retained {default_config.quality_max_findings} of {len(findings)} quality observations.")
        findings = findings[:default_config.quality_max_findings]
    limitations.extend(f"Could not index {path}: {error}" for path, error in index.errors.items())
    policy = {"rules_version": 1, **{k: v for k, v in default_config.model_dump().items() if k.startswith("quality_")}}
    review = QualityReview(
        snapshot_id=index.snapshot_id, policy_id=digest(json.dumps(policy, sort_keys=True)),
        analyzed_files=sorted(index.trees), specialists=list(SPECIALISTS), findings=findings,
        limitations=limitations, unresolved_calls=index.unresolved_calls,
        complete=(bool(index.trees) or repository is None) and not index.errors and not state.get("uninspected_files") and not capped,
    )
    if state.get("quality_baseline_path"):
        compare_baseline(review, repository, state["quality_baseline_path"])
    return {"quality_index": index, "quality_review": review}
