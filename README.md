# SentinelPR

Python code review for pull requests and whole repositories, with optional LLM advice and executable validation.

SentinelPR combines deterministic code rules, an evidence gate, contextual model review, and Markdown/JSON/SARIF/HTML reports. It distinguishes blocking code findings from advisory design suggestions and records why candidates were retained or rejected.

## What it does

- Reviews changed code or all eligible Python files in a local project.
- Checks selected logic, security, defensive-code, architecture, redundancy, performance, readability, and maintainability patterns.
- Uses optional LLM review to evaluate candidates and recommend a change, keep an implementation, or explain missing context.
- Can run linting, type checking, tests, builds, dependency auditing, and secret scanning.
- Exports offline HTML reports and review packets for your existing coding agent.
- Includes a labelled offline benchmark with explicit false-positive and missed-defect metrics.
- Supports automatic PR reviews and manual repository audits through GitHub Actions.

Python is the supported code-analysis language. Checks have limited scope; a clean result does not establish that a project is defect-free or ready for production. See [report interpretation](docs/reports.md).

## Quick start

Requires Python 3.11 or newer. Git is needed for PR review and to honor repository ignore rules. Docker is needed for lint/type/test/build validation and sandboxed PR reproductions.

```sh
git clone https://github.com/PeiyaoTao/SentinelPR.git
cd SentinelPR
python -m venv .venv
```

Activate the environment with `.venv\Scripts\Activate.ps1` in PowerShell or `source .venv/bin/activate` in Bash, then install and review:

```sh
python -m pip install -e .
python -m sentinel.cli --repo . --provider heuristics --markdown review.md
```

This repository command performs static review without model calls or project execution. Read `review.md` for findings, advice, and inspection limitations.

## Common commands

```sh
# Whole-project review, including unchanged Python files
python -m sentinel.cli --repo /path/to/project --provider heuristics --markdown review.md --sarif review.sarif

# Tracked working-tree changes against HEAD
python -m sentinel.cli --git --provider heuristics --markdown review.md

# Committed branch changes against main
python -m sentinel.cli --branch main --provider heuristics --markdown review.md
```

To use a model, configure a provider and model as described in [configuration](docs/configuration.md). Model review sends selected source excerpts to that provider. Cost depends on the configured model, context, and number of calls.

To validate SentinelPR's own checkout as well as review it:

```sh
python -m pip install -e ".[dev,checks]"
docker build -f Dockerfile.checks -t sentinel-checks:local .
python -m sentinel.cli --repo . --provider heuristics --checks all --markdown review.md --sarif review.sarif
```

`--checks all` includes an online dependency audit. Other projects need an image prepared with their dependencies; see [validation](docs/validation.md).

## GitHub Actions

Use the maintained workflow files:

- [Automatic PR review](.github/workflows/sentinel_review.yml)
- [Manual repository audit](.github/workflows/sentinel_repo_audit.yml)

[GitHub setup](docs/github-actions.md) explains credentials, permissions, artifacts, and the current bootstrap fallback that can execute PR checkout code during environment preparation. Review that rollout constraint before enabling the workflow for untrusted contributions.

## Documentation

| Task | Guide |
| --- | --- |
| Run local reviews, use the Python API, manage baselines | [Usage](docs/usage.md) |
| Choose providers, control calls, adjust review limits | [Configuration](docs/configuration.md) |
| Run tests/builds and interpret tool failures | [Validation](docs/validation.md) |
| Configure automation and publication | [GitHub Actions](docs/github-actions.md) |
| Understand findings, decisions, coverage, and exit codes | [Reports](docs/reports.md) |
| Understand the pipeline and implemented rules | [Architecture](docs/architecture.md) |
| Measure current detection behavior | [Benchmarking](docs/benchmarking.md) |
| Review with an existing coding agent | [Delegation](docs/delegation.md) |
| Develop, test, and compare advice models | [Development](docs/development.md) |

The workflow files are the source of truth for YAML configuration. The guides explain their behavior rather than duplicating their contents.

## License

[MIT](LICENSE).
