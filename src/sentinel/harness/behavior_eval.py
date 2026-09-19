"""Measure current repository review behavior; offline by default, live only explicitly."""
import argparse
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path, PurePosixPath
import platform
import statistics
import tempfile
import time

from sentinel.config import default_config
from sentinel.graph import review_repository
from sentinel.offline import offline_mode
from sentinel.harness.behavior_cases import CASES, VERSION


def prediction_rows(state):
    rows = [{"title": f.title, "path": f.file_path, "line": f.start_line,
             "lane": "advisory_observations" if f.category.value == "ANTI_BLOAT" else "defect_leads",
             "proof": f.proof_status.value, "hypothesis": f.hypothesis, "severity": f.severity.value}
            for f in state["verified_findings"]]
    review = state["consolidated_report"].quality_review
    if review:
        rows.extend({"title": f.title, "path": f.evidence[0].location.file_path,
                     "line": f.evidence[0].location.start_line, "lane": "advisory_observations",
                     "proof": f.verification_status, "hypothesis": f.verification_status == "hypothesis",
                     "severity": f.priority} for f in review.findings)
    return rows


def score(expected, predicted):
    # Exact title/path/line labels make scoring reproducible. Each observation
    # can satisfy only one label; duplicated alerts count as extra noise.
    remaining = list(predicted)
    matched, missed = [], []
    for label in expected:
        candidate = next((i for i, row in enumerate(remaining)
                          if all(row[k] == label[k] for k in ("title", "path", "line", "lane"))), None)
        if candidate is None:
            missed.append(label)
        else:
            matched.append(remaining.pop(candidate))
    return {"matched": matched, "missed": missed, "unexpected": remaining}


def metrics(rows, lane):
    tp = sum(sum(f["lane"] == lane for f in row["score"]["matched"]) for row in rows)
    fn = sum(sum(f["lane"] == lane for f in row["score"]["missed"]) for row in rows)
    fp = sum(sum(f["lane"] == lane for f in row["score"]["unexpected"]) for row in rows)
    clean = [row for row in rows if not any(f["lane"] == lane for f in row["expected"])]
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    return {"true_positives": tp, "false_positives": fp, "false_negatives": fn,
            "precision": precision, "recall": recall,
            "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
            "clean_cases": len(clean),
            "clean_cases_with_alerts": sum(any(f["lane"] == lane for f in row["predictions"]) for row in clean)}


def has_gaps(report):
    return bool(report.uninspected_files or
                (report.quality_review is not None and not report.quality_review.complete) or
                any(call["status"] not in {"completed", "cached"} for call in report.llm_usage) or
                report.review_outcome.value in {"INCOMPLETE_REVIEW", "INFRASTRUCTURE_FAILURE"})


def evaluate(cases=CASES, *, live=False):
    rows = []
    with nullcontext() if live else offline_mode():
        config = default_config.model_dump(exclude={"api_key", "llm_cache_dir"})
        for case in cases:
            with tempfile.TemporaryDirectory(prefix="sentinel-benchmark-") as directory:
                root = Path(directory)
                for name, content in case["files"].items():
                    path = PurePosixPath(name)
                    if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
                        raise ValueError("Benchmark paths must be relative")
                    target = root / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content, encoding="utf-8")
                started = time.monotonic()
                state = review_repository(root)
                elapsed = time.monotonic() - started
            report = state["consolidated_report"]
            predictions = prediction_rows(state)
            rows.append({"id": case["id"], "rationale": case["rationale"], "expected": case["expected"],
                         "predictions": predictions, "score": score(case["expected"], predictions),
                         "outcome": report.review_outcome.value, "incomplete": has_gaps(report), "elapsed_seconds": elapsed,
                         "source_hashes": {p: hashlib.sha256(s.encode()).hexdigest() for p, s in case["files"].items()},
                         "report": report.model_dump(mode="json")})
    times = sorted(row["elapsed_seconds"] for row in rows)
    usage = [call for row in rows for call in row["report"]["llm_usage"]]
    known_usage = [c["usage"]["total_tokens"] for c in usage if c.get("usage") and "total_tokens" in c["usage"]]
    package = Path(__file__).parents[1]
    implementation = [(str(p.relative_to(package)), p.read_text(encoding="utf-8")) for p in sorted(package.rglob("*.py"))]
    return {"schema_version": 1, "dataset": VERSION, "dataset_hash": hashlib.sha256(json.dumps(cases, sort_keys=True).encode()).hexdigest(),
            "implementation_hash": hashlib.sha256(json.dumps(implementation).encode()).hexdigest(),
            "python": platform.python_version(), "mode": "live" if live else "offline", "config": config,
            "metrics": {lane: metrics(rows, lane) for lane in ("defect_leads", "advisory_observations")},
            "runtime": {"total_seconds": sum(times), "median_seconds": statistics.median(times) if times else None,
                        "max_seconds": max(times) if times else None,
                        "incomplete_cases": sum(r["incomplete"] for r in rows)},
            "model_usage": {"requests": len(usage), "reported_total_tokens": sum(known_usage) if known_usage or not usage else None,
                            "requests_without_reported_usage": len(usage) - len(known_usage)},
            "cases": rows,
            "limitations": ["Small synthetic repository-mode benchmark, not a population estimate or comparison against another product.",
                            "Defect leads include retained hypotheses; matching a label does not establish proof or live credential validity.",
                            "Exact title/path/line matching is reproducible but requires label review when rules or wording change.",
                            "Advisory observation detection is separate from human-rated advice usefulness. Use quality_eval for contextual disposition comparisons.",
                            "No target tests, builds or dynamic reproductions run in repository mode; this does not measure PR sandbox verification.",
                            "Live mode can call configured models and consume paid tokens. Model coverage is limited by current rules and budgets."]}


def markdown(result):
    lines = ["# SentinelPR behavior benchmark", "", f"Dataset: {result['dataset']} | Mode: {result['mode']}", "",
             "| Track | TP | FP | FN | Precision | Recall | F1 |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for lane, values in result["metrics"].items():
        numbers = [values[k] for k in ("true_positives", "false_positives", "false_negatives", "precision", "recall", "f1")]
        lines.append("| " + lane + " | " + " | ".join("N/A" if n is None else str(round(n, 3)) for n in numbers) + " |")
    lines += ["", "## Per-case gaps", ""]
    for row in result["cases"]:
        lines += [f"- **{row['id']}**: {len(row['score']['matched'])} matched, {len(row['score']['unexpected'])} unexpected, {len(row['score']['missed'])} missed. {row['rationale']}"]
    lines += ["", "## Limits", "", *(f"- {s}" for s in result["limitations"])]
    return "\n".join(lines) + "\n"


def compare(previous, current):
    if previous["dataset_hash"] != current["dataset_hash"]:
        raise ValueError("Benchmark datasets differ; scores are not directly comparable")
    differences = {key: {"previous": previous["config"].get(key), "current": current["config"].get(key)}
                   for key in previous["config"].keys() | current["config"].keys()
                   if previous["config"].get(key) != current["config"].get(key)}
    delta: dict[str, dict[str, float | int | None]] = {}
    for lane in current["metrics"]:
        delta[lane] = {}
        for name in ("true_positives", "false_positives", "false_negatives", "precision", "recall", "f1"):
            before, after = previous["metrics"][lane][name], current["metrics"][lane][name]
            delta[lane][name] = after - before if before is not None and after is not None else None
    return {"same_settings": not differences and previous["mode"] == current["mode"],
            "configuration_changes": differences, "mode_changed": previous["mode"] != current["mode"],
            "metric_delta": delta, "previous_implementation": previous["implementation_hash"],
            "current_implementation": current["implementation_hash"],
            "note": "Positive FP/FN deltas are regressions; score changes with different settings are confounded. Runtime and model outputs can vary between runs."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Explicitly enable configured model calls")
    parser.add_argument("--output", type=Path, default=Path("sentinel-artifacts/behavior-baseline.json"))
    parser.add_argument("--compare", type=Path, help="Compare against a saved run of the same dataset")
    args = parser.parse_args()
    if args.live and default_config.provider == "heuristics":
        parser.error("Configure a model provider before using --live")
    result = evaluate(live=args.live)
    if args.compare:
        result["comparison"] = compare(json.loads(args.compare.read_text(encoding="utf-8")), result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    args.output.with_suffix(".md").write_text(markdown(result), encoding="utf-8")
    print(json.dumps(result["metrics"], indent=2))


if __name__ == "__main__":
    main()
