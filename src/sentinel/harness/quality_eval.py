"""Small labeled advice benchmark, with explicit live calls or saved-response replay."""
import argparse
import json
from pathlib import Path
from sentinel.config import default_config
from sentinel.llm import get_llm_client
from sentinel.quality.contextual import assess_group
from sentinel.quality.index import RepositoryIndex
from sentinel.quality.models import Evidence, QualityFinding, SourceLocation

# These labels are review judgments for regression/comparison, not universal design truths.
CASES = [
    {"id": "necessary_cases", "expected": "keep", "rule": "maintainability.branch-complexity",
     "observation": "Several branches classify distinct exit codes.",
     "source": "def classify(code):\n    if code == 0: return 'passed'\n    if code == 1: return 'failed'\n    if code in (2, 3, 4, 5): return 'incomplete'\n    return 'error'\n"},
    {"id": "boundary_validation", "expected": "keep", "rule": "maintainability.branch-complexity",
     "observation": "A public raw-input handler contains validation branches.",
     "source": "def parse_request(raw):\n    if not isinstance(raw, dict): raise ValueError('object required')\n    count = raw.get('count')\n    if type(count) is not int: raise ValueError('integer required')\n    if not 1 <= count <= 100: raise ValueError('count out of range')\n    return count\n"},
    {"id": "separable_calculation_io", "expected": "recommend", "rule": "maintainability.branch-complexity",
     "observation": "One function calculates order charges and writes a receipt; testing the charge calculation requires a file write.",
     "source": "def charge_order(items, receipt_path):\n    total = 0\n    for price, quantity in items:\n        amount = price * quantity\n        if quantity >= 10: amount *= 0.9\n        total += amount\n    with open(receipt_path, 'w') as stream:\n        stream.write(str(total))\n    return total\n"},
    {"id": "unknown_client_contract", "expected": "inconclusive", "rule": "performance.repeated-call",
     "observation": "A client method is called inside a loop. Its implementation, ordering requirements and batching contract are unavailable.",
     "source": "def deliver(client, items):\n    for item in items:\n        client.send(item)\n"},
]


def case_input(case):
    index = RepositoryIndex({"subject.py": case["source"]})
    loc = SourceLocation(file_path="subject.py", start_line=1, end_line=len(case["source"].splitlines()))
    finding = QualityFinding(rule_id=case["rule"], category="maintainability", priority="medium",
        title="Review this observation", explanation=case["observation"], trigger_conditions="Supplied source structure",
        recommendation="Evaluate whether a change is justified.", subject=case["id"], fingerprint=case["id"],
        evidence=[Evidence(kind="ast", description=case["observation"], location=loc, source_hash=index.hashes["subject.py"])],
        verification_status="observed", confidence="high")
    return [finding], index


class RecordingClient:
    def __init__(self, client):
        self.client = client
        self.response = ""

    def complete(self, *args, **kwargs):
        self.response = self.client.complete(*args, **kwargs)
        return self.response


class ReplayClient:
    def __init__(self, response):
        self.response = response

    def complete(self, *args, **kwargs):
        return self.response


def evaluate(config, responses=None, client=None):
    rows, captured = [], {}
    for case in CASES:
        group, index = case_input(case)
        reviewer = RecordingClient(ReplayClient(responses[case["id"]]) if responses is not None else client)
        item, called = assess_group(group, index, config, reviewer)
        actual = item.decision.disposition if item.decision is not None else item.status
        captured[case["id"]] = reviewer.response
        rows.append({"id": case["id"], "expected": case["expected"], "actual": actual,
                     "matches_reference": actual == case["expected"], "call_attempted": called,
                     "assessment": item.model_dump(mode="json")})
    return {
        "provider": config.provider, "model": config.frontier_model, "context_budget": config.llm_quality_context_chars,
        "cases": rows, "responses": captured,
        "metrics": {"total": len(rows), "matches_reference": sum(r["matches_reference"] for r in rows),
                    "invalid_or_unavailable": sum(r["actual"] not in {"recommend", "keep", "inconclusive"} for r in rows),
                    "false_recommendations": sum(r["expected"] != "recommend" and r["actual"] == "recommend" for r in rows),
                    "missed_recommendations": sum(r["expected"] == "recommend" and r["actual"] != "recommend" for r in rows)},
        "limitations": "Small subjective advice benchmark. Valid citations and matching dispositions do not prove recommendation usefulness; inspect recorded rationales and actions. Existing defect benchmarks measure separate behavior.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", action="store_true", help="Call the configured frontier model on four fixed fixtures")
    mode.add_argument("--responses", type=Path, help="Replay the responses field from a saved evaluation JSON")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.live and default_config.provider == "heuristics":
        parser.error("Set SENTINEL_LLM_PROVIDER and the desired FRONTIER_MODEL for live evaluation")
    saved = json.loads(args.responses.read_text(encoding="utf-8")) if args.responses else None
    config = default_config.model_copy(deep=True)
    if saved is not None:
        config.provider, config.frontier_model = saved["provider"], saved["model"]
        config.llm_quality_context_chars = saved["context_budget"]
    result = evaluate(config, responses=saved["responses"] if saved else None,
                      client=get_llm_client(tier="frontier") if args.live else None)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result["metrics"]))


if __name__ == "__main__":
    main()
