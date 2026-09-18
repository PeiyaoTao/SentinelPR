# GitHub Actions

[Back to README](../README.md) · [Configuration](configuration.md) · [Validation](validation.md)

The YAML files are the executable source of truth. This guide describes setup and behavior; copy maintained workflows rather than an embedded documentation snapshot.

| Workflow | Trigger | Results |
| --- | --- | --- |
| [sentinel_review.yml](../.github/workflows/sentinel_review.yml) | PR opened, updated, or reopened | GitHub review when permitted; Markdown, SARIF, and JSON artifacts |
| [sentinel_repo_audit.yml](../.github/workflows/sentinel_repo_audit.yml) | Manual dispatch | Job summary, Markdown/SARIF artifacts, attempted Code Scanning upload |

Both workflows use Python 3.11, a prepared check image, all six validation checks, and a 30-minute job timeout. Repository/org settings can restrict write operations and artifact publication.

## Setup

1. Make the reviewer package, pinned requirements, and `Dockerfile.checks` available on the trusted base branch before relying on PR review. Read the bootstrap constraint below.
2. The PR workflow declares `contents: read`, `pull-requests: write`, and `issues: write`. Permit the declared operations through repository/organization policy, including bot PR approvals if you intend to use automatic approval. The manual audit declares `contents: read` and `security-events: write`.
3. For model review, add the chosen provider's key as an Actions secret: `DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, or `GEMINI_API_KEY`. Set the provider/model variables described below. For offline heuristics, explicitly set `SENTINEL_LLM_PROVIDER=heuristics`.
4. Run **SentinelPR Repository Audit** on a trusted branch for an initial full-project report. Once the reviewer is on the base branch, an eligible PR event runs **SentinelPR Auto Code Review**.

The workflows already request permissions; avoid broadening unrelated token permissions. Secret availability and repository policy may still prevent model calls or publication.

## Variables forwarded by both workflows

| Actions variable | Default when unset | Effect |
| --- | --- | --- |
| `SENTINEL_LLM_PROVIDER` | Auto-detection from available provider keys | Select provider, or `heuristics` |
| `FRONTIER_MODEL` | Provider configuration default | Model for optional review stages |
| `FAST_MODEL` | Provider configuration default | Legacy tier configuration/report label; current stages use frontier |
| `SENTINEL_BASE_URL` | Provider endpoint | Custom compatible endpoint |
| `SENTINEL_LLM_CRITIC` | `true` | Enable code-finding contextual critic |
| `SENTINEL_LLM_QUALITY` | `true` | Enable contextual quality advice |
| `SENTINEL_QUALITY_MAX_GROUPS` | `5` | Maximum additional quality calls; `0` prevents calls |
| `SENTINEL_QUALITY_CONTEXT_CHARS` | `18000` | Quality observation/excerpt payload budget |

The YAML also contains some legacy secret fallbacks for configuration values; prefer variables for non-secret settings. A library environment variable is not automatically an Actions repository variable: only values explicitly forwarded by a workflow reach its process. For example, the provided workflows forward provider-specific keys, not the generic `SENTINEL_API_KEY` override.

## PR revisions and environment preparation

The PR workflow normally installs reviewer code/dependencies from the event's base SHA and builds the check image from that checkout. It checks out the exact head SHA separately. Review input is the merge-base-to-head diff and the corresponding changed base/head blobs; project validation materializes the full head snapshot. Git blob limits are 5,000 files, 2 MB per file, and 32 MB total per collection.

**Current bootstrap constraint:** if the base checkout lacks `requirements-audit.txt`, the workflow can install dependencies and the reviewer package from the PR checkout. If it lacks `Dockerfile.checks`, it can build an image from the PR checkout. These steps execute checkout-controlled installation/build instructions on the runner before the isolated checks. Do not rely on those fallback paths to review untrusted contributions. Ensure required files exist on the trusted base and review changes to the workflow itself.

The manual audit installs and builds from the selected branch too; run it only on a branch you trust. To adopt SentinelPR in another repository, use a separately pinned, trusted reviewer checkout and an image prepared for that target's dependencies. The included workflows are configured for SentinelPR's own repository.

## Publication and outcomes

The GitHub entry point checks that the PR is open and both base/head SHAs are current before and after analysis. A detected revision change prevents publication; artifacts produced before the second check are retained. Runs for the same PR cancel earlier in-progress jobs through workflow concurrency settings.

| Final review state | Published review event when enabled |
| --- | --- |
| `CHANGES_REQUIRED` | Request changes |
| `INCOMPLETE_REVIEW` or `INFRASTRUCTURE_FAILURE` | Comment |
| `CLEAN` with retained code findings | Comment |
| `CLEAN` with no retained code findings | Approve |

Specialist quality observations remain advisory and do not themselves prevent approval. A `CLEAN` outcome only describes the supported checks; see [report interpretation](reports.md). If the review API rejects a submission, the entry point attempts an informational issue comment and retains the outcome's exit code.

The provided workflow disables publication for fork and Dependabot PRs and attempts artifact upload even after failure. Missing model credentials can limit model review. PR artifacts are named `sentinel-pr-review`; manual audit artifacts are `sentinelpr-repo-review`. Manual Code Scanning upload is allowed to fail independently, so check that step's result rather than assuming a SARIF file was published.
