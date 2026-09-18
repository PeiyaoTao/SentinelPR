# Executable project validation

[Back to README](../README.md) · [Outcome meanings](reports.md) · [GitHub execution](github-actions.md)

Repository review is static by default. `--checks` explicitly runs validation tools and attaches their results to the final report. Locally it requires `--repo`; the GitHub PR entry point runs checks against the full immutable head snapshot.

## Prepare and run

For this SentinelPR checkout, with Docker running:

```sh
python -m pip install -e ".[dev,checks]"
docker build -f Dockerfile.checks -t sentinel-checks:local .
python -m sentinel.cli --repo . --provider heuristics --checks all --markdown review.md --sarif review.sarif
```

The maintained [Dockerfile.checks](../Dockerfile.checks) prepares this project's pinned dependencies. Another target needs a trusted image containing its runtime, test, build, and validation dependencies. Supply that image with `--check-image YOUR_IMAGE`; the runner does not install missing packages while executing the target.

```sh
python -m sentinel.cli --repo . --provider heuristics --checks dependencies,secrets
python -m sentinel.cli --repo . --provider heuristics --checks lint,types,tests,build --check-timeout 300
```

| Check | What runs | Scope |
| --- | --- | --- |
| `lint` | Ruff | Target configuration; this repository enables correctness rules |
| `types` | mypy | Target configuration; this repository checks bodies of untyped functions too |
| `tests` | pytest | Actual collected suite; no coverage measurement is requested |
| `build` | `python -m build --no-isolation` | Builds an sdist and wheel with already-prepared dependencies |
| `dependencies` | pip-audit | Known vulnerabilities in supplied exact pins; queries an online service |
| `secrets` | Local patterns | Selected credential formats in the current snapshot, with values withheld |

## Execution boundaries

Lint, types, tests, and build run as an unprivileged user in disposable, network-disabled containers. A snapshot is streamed through standard input, with no host mounts. The runner applies a read-only root filesystem, temporary storage, resource limits, and a timeout. It uses an existing local image rather than pulling one during the check.

Image preparation is a separate operation that installs dependencies and can use the network. Build the image from trusted inputs. Before executing tools, the container checks installed versions against supplied pins and declared runtime/build requirements. Missing or mismatched dependencies produce an incomplete result.

The runner withholds raw tool output because tests and build hooks can print source or credentials. It exports supported diagnostic codes and locations. Run a tool directly only in a checkout you trust when you need its full output.

Validation snapshots are limited to 5,000 files, 2 MB per file, and 32 MB total. They omit dependency/build/VCS directories and do not follow links. Relevant linked, unreadable, or over-budget files make otherwise passing checks incomplete. Git-tracked files are included even when ignored; ignored untracked files are excluded.

## Dependency and secret scanning

Dependency scanning runs without Docker. It sends package names and versions from a sanitized temporary requirements file to the vulnerability service. `--requirements PATH` selects the pins file relative to the target; the default is [requirements-audit.txt](../requirements-audit.txt).

Supported input is exact `name==version` pins and comments. Ranges, URL/VCS requirements, recursive includes, hashes, and environment markers currently produce an incomplete result. Include transitive dependencies: a clean audit of incomplete pins cannot establish that the full dependency graph is clear.

To refresh this project's pins, install `pip-tools` separately, review the regenerated file, then rebuild the image:

```sh
pip-compile --extra dev --extra checks --strip-extras --no-emit-index-url --no-emit-trusted-host --output-file requirements-audit.txt pyproject.toml
```

Secret scanning also needs no Docker or network. It recognizes private-key headers and selected GitHub, AWS, and Slack patterns. It scans the current snapshot, not Git history or every credential format. Results contain locations and rule identifiers without credential values.

## Troubleshooting

| Reported condition | Next step |
| --- | --- |
| Docker unavailable | Start a usable Docker engine; the runner does not fall back to host execution |
| Check image or tool unavailable | Build the prepared image and verify its tag and installed tools |
| Prepared dependencies do not match | Update the trusted image for the target's pins and declared requirements |
| Tests did not complete | Inspect collection/configuration errors or missing offline fixtures; zero collected tests is incomplete |
| Check timed out | Investigate the workload, then adjust `--check-timeout` if appropriate |
| Dependency scan incomplete | Check exact-pin syntax, pin completeness, and network access |
| Source omitted from snapshot | Resolve read/link/budget limitations before treating passing tools as a complete run |

A test assertion failure or build failure is a failed check. Collection errors, missing environments, and incomplete execution do not establish a code defect. See [reports](reports.md) for how tool status affects the final outcome.

PR reproduction tests use a different [sandbox harness](../src/sentinel/harness/sandbox.py). It uses a read-only mount of a temporary reproduction file and a pytest-capable image; it does not use the validation runner's streamed snapshot. The harness defaults to `python:3.11-slim` and does not install pytest; reproduction can fail setup unless the selected image already includes it. The harness accepts a prepared image through its Python API. Repository review never invokes this reproduction stage.
