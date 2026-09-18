# Running reviews

[Back to README](../README.md) · [Configuration](configuration.md) · [Reports](reports.md)

## Choose a scope

Run commands from an activated environment with SentinelPR installed. `--repo`, `--git`, `--branch`, and `--diff-file` are mutually exclusive.

| Mode | Input |
| --- | --- |
| `--repo PATH` | Eligible files in the local working directory, including non-ignored untracked files. Omitting PATH uses the current directory. |
| `--git` | `git diff HEAD`: staged and unstaged changes to tracked files, with current file contents and HEAD base files. |
| `--branch main` | `git diff main...HEAD`: committed branch changes. Source is loaded from HEAD and the named base ref. |
| `--diff-file change.patch` | A unified diff, with matching files read from the working directory when available. Missing files are reconstructed from hunks, so context can be incomplete. |

With no mode, the CLI reviews uncommitted tracked changes. An empty diff exits without a report. `--branch` loads base source from the named ref; the GitHub entry point instead uses the merge-base source. For exact control, supply matching diff/base/head snapshots through the Python API.

```sh
python -m sentinel.cli --repo . --provider heuristics --markdown review.md --sarif review.sarif
python -m sentinel.cli --git --provider heuristics --markdown changes.md
python -m sentinel.cli --diff-file change.patch --provider heuristics --sarif changes.sarif
python -m sentinel.cli --help
```

Create output parent directories first. The CLI exports Markdown and SARIF; the Python API also exposes a structured report. GitHub PR runs save JSON automatically.

## Repository scope

Repository mode honors Git ignore rules and includes tracked files plus non-ignored untracked files. Plain directories use built-in exclusions for dependencies, virtual environments, build outputs, and version-control metadata. Links and junctions are not followed. Avoid concurrent edits when you need consistent source contents.

Python files receive code analysis. Recognized README, packaging, requirements, and CI files provide project context. Secret/private-key files are excluded from repository model/static context. The separate [secret scanner](validation.md) can inspect tracked credentials while reporting locations without values.

Unsupported source languages, parse errors, read failures, and budget omissions are disclosed. Empty or documentation-only repositories produce an incomplete code review. The default repository graph does not import project modules, run tests/builds, or execute reproduction scripts; use `--checks` for validation. PR mode can attempt a supported reproduction in Docker even with `--provider heuristics`.

## Model-assisted review

Configure a reachable provider using the [configuration guide](configuration.md), then run a normal review. For example, with a local model already installed and served:

```sh
python -m sentinel.cli --repo . --provider ollama --model YOUR_LOCAL_MODEL --base-url http://localhost:11434/v1 --markdown review.md
```

Replace `YOUR_LOCAL_MODEL` with an available model identifier. `--no-llm-critic` disables contextual criticism of code findings; `--no-llm-quality` disables contextual quality advice. Repository project assessment remains enabled by the configured provider. `--provider heuristics` disables all model stages.

## Python API

```python
from sentinel.graph import review_pr, review_repository

result = review_repository(".")
report = result["consolidated_report"]
print(report.summary_markdown)
print(report.model_dump_json(indent=2))

# Supply a unified diff and matching full source files for a PR review.
# Additional surrounding modules can improve cross-file context.
# result = review_pr(diff=diff_text, head_files=head_files, base_files=base_files)
```

`review_repository(path, baseline_path=None)` and `review_pr(diff, head_files, base_files=None, uninspected_files=None)` return graph state. `consolidated_report` contains exports; `verified_findings` contains retained code findings. Retained findings can still be advisory hypotheses, so inspect their proof status and severity.

These API calls do not run the six project validation checks. To attach them explicitly:

```python
from sentinel.checks.report import attach_validation
from sentinel.checks.runner import run_checks

attach_validation(report, run_checks(".", ["secrets"]))
```

## Repository quality baselines

```sh
python -m sentinel.cli --repo . --provider heuristics --save-baseline quality-baseline.json
python -m sentinel.cli --repo . --provider heuristics --baseline quality-baseline.json --markdown review.md
```

Baselines classify specialist observations as new, existing, resolved, or unassessed. They are bound to the repository directory and static specialist policy. Fingerprints survive unrelated line insertions, while changes to semantic subjects or group membership can create new fingerprints.

Incomplete scans cannot overwrite a baseline; skipped or excluded source cannot establish that a previous observation is resolved. Use `--save-baseline` explicitly after reviewing the new state. Contextual model decisions preserve the underlying static fingerprints.

See [reports](reports.md) for outcome precedence and CLI exit codes.
