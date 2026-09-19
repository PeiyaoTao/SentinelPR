# Benchmarking review behavior

[Back to README](../README.md) · [Development](development.md) · [Delegation](delegation.md)

## Reproduce the offline baseline

```sh
python -m sentinel.harness.behavior_eval --output sentinel-artifacts/behavior-baseline.json
```

This runs 12 hand-labelled repository fixtures through the real static review pipeline and writes JSON plus a Markdown summary. Model calls are disabled even when credentials are configured. The reviewed fixture files are never imported or executed. This repository-mode benchmark does not test Docker reproductions or executable validation.

The fixtures include mutable-state leakage and a read-only default counterexample, interpolated/parameterized SQL, a fabricated secret fixture, a credential-shaped assignment in a test, synchronized global mutation, mandatory perimeter validation, incorrect/correct indexing and unreachable-code advice. The indexing defect deliberately measures an unsupported detection case. Labels describe desired behavior rather than asserting every current rule succeeds.

## Metrics and interpretation

- **Defect leads:** retained LOGIC/SECURITY findings, including hypotheses. Precision/recall describe alert matching, not how many bugs have been independently proved.
- **Advisory observations:** anti-bloat and static quality signals scored separately. Their detection does not establish that a refactor is useful.
- **Noise:** unexpected observations and clean cases receiving alerts.
- **Coverage and cost:** operationally incomplete outcomes, elapsed time, per-case reports, request statuses and provider-reported token usage.
- **Provenance:** dataset and reviewer implementation hashes, Python version, sanitized configuration and fixture source hashes.

Matching requires exact title, path, line and track, with one prediction per expected observation. Duplicate predictions count as additional noise. Review the labels when changing rule names or locations. Zero-denominator metrics are unavailable, not perfect scores. Latency includes collection and pipeline work on this machine; it is not a production CI estimate. An otherwise CLEAN case can still contain a missed labelled defect.

The initial offline run reports 3 matched defect leads, 2 unexpected alerts and 1 missed defect: precision 0.60, recall 0.75, F1 0.667. The unexpected alerts are the read-only default and synchronized global update; the missed defect is indexing at `len(items)`. Advisory results cover only one positive fixture, so a perfect advisory score says very little. Use the generated JSON as the reproducible result; this small synthetic dataset does not establish general superiority or production accuracy.

## Compare changes or models

```sh
python -m sentinel.harness.behavior_eval --compare sentinel-artifacts/behavior-baseline.json --output sentinel-artifacts/behavior-next.json
```

Comparison rejects changed datasets and records metric deltas and configuration differences. Different settings are flagged as a confounded comparison. A benchmark command completing is not a passing quality threshold; inspect false positives, misses and individual reports.

Model evaluation is opt-in after configuring a provider:

```sh
python -m sentinel.harness.behavior_eval --live --output sentinel-artifacts/behavior-live.json
```

This uses the configured critic/quality/project models and consumes their usage allowance. It does not change how deterministic candidates are discovered. Hold dataset and budgets constant for comparisons, repeat live runs to examine variability, and inspect incomplete responses rather than hiding them from the denominator. Missing provider usage is reported separately from the sum of known usage; that sum is not necessarily total cost.

The existing [four-case advice evaluation](development.md#comparing-advice-models) measures keep/recommend/inconclusive judgments separately. Human review is still needed to score recommendation usefulness. AACR-Bench ingestion, large real-PR corpora and external-tool comparisons are not implemented in this first baseline.
