"""Explicit ordering for static signals and contextual, advisory recommendations."""
from sentinel.quality.models import QualityFinding, ContextualAdvice

METRIC_RULES = {"maintainability.branch-complexity", "readability.deep-nesting", "readability.long-function"}


def group_observations(findings: list[QualityFinding]) -> list[list[QualityFinding]]:
    """Group same-symbol metrics for presentation; preserve every source finding."""
    groups: dict[tuple, list[QualityFinding]] = {}
    for finding in findings:
        anchors = tuple((e.location.file_path, e.location.start_line, e.location.end_line, e.source_hash) for e in finding.evidence)
        key = (finding.subject, anchors) if finding.rule_id in METRIC_RULES else (finding.fingerprint,)
        groups.setdefault(key, []).append(finding)
    priority = {"high": 0, "medium": 1, "low": 2}
    for group in groups.values():
        group.sort(key=lambda f: (priority[f.priority], f.rule_id))
    return sorted(groups.values(), key=lambda group: (
        priority[group[0].priority], not any(f.lifecycle == "new" for f in group),
        -len(group), group[0].subject, group[0].fingerprint,
    ))



def ranked_recommendations(items: list[ContextualAdvice]) -> list[ContextualAdvice]:
    """Only cited, validated recommend decisions qualify; estimates remain model opinions."""
    levels = {"high": 0, "medium": 1, "low": 2}
    candidates = [item for item in items if item.status == "reviewed" and item.decision is not None
                  and item.decision.disposition == "recommend"]
    def key(item):
        decision = item.decision
        assert decision is not None
        return levels[decision.impact], levels[decision.confidence], levels[decision.benefit], item.subject
    return sorted(candidates, key=key)


def review_selection(groups, index):
    """Known source relationships prioritize context retrieval; unresolved reach is unknown."""
    priorities = {"high": 0, "medium": 1, "low": 2}
    def reach(group):
        locations = [e.location for f in group for e in f.evidence]
        paths = {loc.file_path for loc in locations}
        users = {edge.source for edge in index.dependencies if edge.target in paths}
        for symbol in index.functions():
            if any(loc.file_path == symbol.location.file_path and symbol.location.start_line <= loc.start_line <= symbol.location.end_line for loc in locations):
                users.update(caller.location.file_path for caller in index.get_callers(symbol.id))
        return len(users - paths)
    scored = [(group, reach(group)) for group in groups]
    scored.sort(key=lambda pair: (priorities[pair[0][0].priority], -pair[1],
                                 not any(f.lifecycle == "new" for f in pair[0]), -len(pair[0]), pair[0][0].subject))
    return [(group, f"Rule priority {group[0].priority}; {count} known other indexed file(s) importing or calling the observed code. Unresolved relationships are unknown.") for group, count in scored]
