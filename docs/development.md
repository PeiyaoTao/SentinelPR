# Development and evaluation

[Back to README](../README.md) · [Architecture](architecture.md) · [Configuration](configuration.md)

Use a trusted checkout and an activated Python 3.11+ environment. Project instructions are in [AGENTS.md](../AGENTS.md).

## Local checks

```sh
python -m pip install -e ".[dev,checks]"
python -m pytest -q
python -m ruff check .
python -m mypy src
python -m build --no-isolation
```

These developer commands execute directly in your environment. For validation of a target through the isolated runner, use the [validation guide](validation.md). Tests include platform-dependent skips; a skip is not a successful verification of that platform behavior.

The synthetic defect benchmark has six labeled cases: mutable defaults, internal ghost checks, required perimeter validation, SQL injection, clean refactoring, and perimeter changes without changed test files.

```sh
python -m sentinel.harness.eval_suite
```

Use heuristics mode for deterministic offline evaluation, for example `$env:SENTINEL_LLM_PROVIDER = 'heuristics'` in PowerShell or `export SENTINEL_LLM_PROVIDER=heuristics` in Bash. The benchmark checks expected review behavior; it is not evidence that all possible defects are detected.

## Comparing advice models

The [quality evaluation harness](../src/sentinel/harness/quality_eval.py) has four fixed reference cases:

| Case | Reference judgment |
| --- | --- |
| Necessary exit-code handling | Keep |
| Mandatory input validation | Keep |
| Separable calculation and receipt I/O | Recommend a specific separation |
| Unknown client contract inside a loop | Inconclusive |

After configuring a provider/key, choose the model to evaluate and save a distinct output for each model. PowerShell example:

```powershell
$env:SENTINEL_LLM_PROVIDER = 'deepseek'
$env:FRONTIER_MODEL = 'YOUR_SUPPORTED_MODEL'
python -m sentinel.harness.quality_eval --live --output sentinel-artifacts/quality-model-a.json
python -m sentinel.harness.quality_eval --responses sentinel-artifacts/quality-model-a.json --output sentinel-artifacts/quality-model-a-replay.json
```

Replace the model placeholder. `--live` explicitly makes model calls on the fixed fixtures. `--responses` replays saved responses without model calls. Inspect each output's metrics; an evaluation process completing is not a passing quality threshold.

Outputs record model identity, context budget, responses, source hashes/ranges, assessments, reference matches, false recommendations, missed recommendations, and invalid/unavailable responses. For useful comparisons, hold fixture/code version and context settings constant, and inspect the proposed actions and reasoning as well as counts.

The labels are small, subjective reference judgments. Matching a disposition and citing a supplied line do not prove usefulness. Unit tests use controlled responses to verify budgets, validation, exports, and outcome rules; those tests do not measure a live provider's review quality.

## Code map

| Responsibility | Source |
| --- | --- |
| CLI and graph entry points | [cli.py](../src/sentinel/cli.py), [graph.py](../src/sentinel/graph.py) |
| Settings and report schemas | [config.py](../src/sentinel/config.py), [state.py](../src/sentinel/state.py) |
| Collection and immutable Git input | [repository.py](../src/sentinel/repository.py), [git_snapshot.py](../src/sentinel/git_snapshot.py) |
| Candidate rules, critic, and project assessment | [agents/](../src/sentinel/agents/) |
| Static quality rules and contextual review | [quality/](../src/sentinel/quality/) |
| Tool execution and outcome attachment | [checks/](../src/sentinel/checks/) |
| Model adapter | [llm.py](../src/sentinel/llm.py) |
| GitHub publication | [github.py](../src/sentinel/github.py) |
| Reproductions and evaluations | [harness/](../src/sentinel/harness/) |
| Regression suite | [tests/](../tests/) |

When behavior changes, update the relevant guide and link to maintained code/configuration. Keep the README focused on getting started, avoid copying entire workflow files, and distinguish tested behavior from planned capabilities.
