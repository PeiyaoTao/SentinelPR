# SentinelPR: Autonomous Code Reviewer & PR Quality Gate

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![LangGraph](https://img.shields.io/badge/Orchestration-LangGraph-orange.svg)](https://github.com/langchain-ai/langgraph)
[![AST Engine](https://img.shields.io/badge/AST-Python%20ast-green.svg)](https://docs.python.org/3/library/ast.html)

SentinelPR is an autonomous multi-agent code reviewer built with LangGraph, deterministic Python AST slicing, optional Docker container test verification with host-execution refusal, an active Anti-Bloat / Fail-Fast Auditor calibrated by trust boundaries, an adversarial critic gate, and a diff-hunk offset validator.

---

## Key Capabilities

1. **Python AST Slicing**: Slices post-change Python files into symbol-level AST scopes using Python's standard library `ast` module, isolating enclosing function/class boundaries, decorators, and imports for high-precision token efficiency.
2. **Deterministic Rules + LLM Reasoning Hybrid**: Combines deterministic rules (fast AST boundary checks, cyclomatic complexity calculations, safe diff hunk mapping, and container isolation) with LLM semantic reasoning (concurrency bugs, taint tracking, and adversarial critique) for zero-hallucination reviews.
3. **Trust-Zone Aware Anti-Bloat**: Enforces the **Fail-Fast Principle** by flagging ghost null-checks, redundant validations, and swallowed exceptions in internal domain code without breaking mandatory defensive validations at public perimeter boundaries.
4. **Adversarial Critic Gate**: Acts as defense counsel for the author to eliminate false alarms and nitpicks, applying a severity-tiered standard of proof before publishing findings.
5. **Gated Container Test Verification**: Formulates minimal standalone pytest scripts for candidate logic findings and executes them in an isolated, network-disabled Docker container when available. If Docker is unavailable in the environment, SentinelPR safely marks dynamic proof as unavailable and relies strictly on static AST and critic analysis, completely refusing host execution of untrusted PR code.
6. **Diff-Hunk Offset Validator & Safe Replacements**: Accurately maps candidate finding line numbers against git patch hunks to eliminate GitHub API 422 errors, and guarantees that interactive GitHub ````suggestion```` blocks only output syntax-verified code replacements.
7. **Token-Optimized Architecture**: Prunes surrounding source context down to changed symbol scopes, pre-filters noisy files (lockfiles, minified code, assets), and routes tasks across model tiers to keep typical PR review costs at a few cents.

---

## Language Scope & Roadmap

- **Python (Active AST Engine)**: Symbol-level AST slicing, trust zone classification, decorator preservation, and fail-fast anti-bloat analysis are powered natively by Python's standard `ast` module.
- **Polyglot Expansion (Roadmap)**: Non-Python source files are currently analyzed via unified diff hunks and risk heuristics. Multi-language AST slicing via Tree-sitter is planned on the future roadmap.

---

## Architecture Flow

```
                     [Raw Git Diff + Base/Head Files]
                                    |
                          +---------v---------+
                          |   Triage Agent    | <-- Noise Filter (Lockfiles, Minified)
                          |  (AST & Boundary) | <-- Full-File AST Symbol Slicer
                          +---------+---------+ <-- Trust Zone Classifier
                                    |
                    +---------------+---------------+
                    |               |               |
                    v               v               v
             +--------------+ +--------------+ +--------------+
             | Logic Agent  | |Security Agent| |  Anti-Bloat  |
             |(Concurrency, | |(Taint, Sanit-| |   Auditor    |
             | State, Flaws)| |ization, Auth)| | (Trust-Aware)|
             +------+-------+ +------+-------+ +------+-------+
                    |               |               |
                    +---------------+---------------+
                                    |
                                    v (Annotated operator.add)
                    +-------------------------------+
                    |     Test Synthesis Loop       | <-- 1-2 Repair Retries on Syntax/Import Err
                    |     (Isolated Test Sandbox)   | <-- Dynamic Proof for Logic Findings
                    +---------------+---------------+
                                    |
                                    v
                    +-------------------------------+
                    |    Adversarial Critic Gate    | <-- Tiered Burden of Proof (Batched)
                    +---------------+---------------+
                                    |
                                    v
                    +-------------------------------+
                    |      Consolidator Agent       | <-- Diff Hunk Offset Validator
                    +-------+---------------+-------+
                            |               |
                    [GitHub Inline/PR]   [SARIF Report]
```

---

## Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/PeiyaoTao/SentinelPR.git
cd SentinelPR

# Install dependencies in editable mode
pip install -e ".[dev]"
```

---

## Usage

### Option A: Command-Line Interface (CLI)

Review uncommitted changes, feature branches, or exported patch files directly from your terminal:

```bash
# Review uncommitted changes in current repository
python -m sentinel.cli --git

# Review a branch against main
python -m sentinel.cli --branch main

# Review a patch file and export SARIF 2.1.0 report
python -m sentinel.cli --diff-file changes.patch --sarif report.sarif
```

### Option B: Local Models (Ollama / vLLM / LMStudio)

SentinelPR natively supports OpenAI-compatible endpoints with zero extra dependencies:

```bash
# 1. Start your local Ollama model
ollama run qwen2.5-coder:7b

# 2. Run review using local Ollama
python -m sentinel.cli --git --provider ollama --model qwen2.5-coder:7b
```

### Option C: Cloud LLMs (DeepSeek, OpenAI, Gemini)

Configure your API key via environment variables:

```bash
# Using DeepSeek (high coding performance & low cost)
export SENTINEL_LLM_PROVIDER="deepseek"
export DEEPSEEK_API_KEY="sk-..."
python -m sentinel.cli --git --provider deepseek --model deepseek-chat

# Using OpenAI
export SENTINEL_LLM_PROVIDER="openai"
export OPENAI_API_KEY="sk-..."
python -m sentinel.cli --git --provider openai --model gpt-4o-mini

# Using Google Gemini
export SENTINEL_LLM_PROVIDER="gemini"
export GEMINI_API_KEY="..."
python -m sentinel.cli --git --provider gemini --model gemini-2.0-flash
```

*(On Windows PowerShell, use `$env:SENTINEL_LLM_PROVIDER="openai"` syntax).*

### Option D: Python API

Integrate SentinelPR directly into custom services, webhooks, or CI pipelines:

```python
from sentinel.graph import review_pr

diff_text = """... unified git diff ..."""
head_files = {
    "services/cart.py": "... post-change file contents ...",
}

result = review_pr(diff=diff_text, head_files=head_files)
report = result["consolidated_report"]

print(report.summary_markdown)
print(f"Accepted findings: {report.accepted_findings_count}")
for comment in report.inline_comments:
    print(f"Inline [{comment['path']}:{comment['line']}]: {comment['body']}")
```

---

## GitHub PR Automated Review (GitHub Actions)

SentinelPR operates as an automated GitHub Pull Request quality gate. When configured in your repository, SentinelPR triggers whenever a PR is opened, updated, or reopened, analyzes the diff against surrounding code, and posts high-signal reviews.

### Features in GitHub Reviews

- **Zero-Noise Approvals**: If a PR is clean and adheres to standards, SentinelPR approves the PR with an executive summary and posts 0 inline nitpicks.
- **1-Click Interactive Suggestions**: Actionable findings include GitHub native `suggestion` blocks on the **Files changed** tab, allowing authors to commit verified fixes directly in the browser.
- **PR Risk & Blast Radius Analysis**: Every review quantifies cyclomatic complexity deltas, lines of churn, public perimeter symbol exposure, and verifies whether matching unit tests were added.
- **Engine Transparency**: Review comments clearly state the active LLM provider and model tier.

### Step-by-Step GitHub Setup Guide

#### Step 1: Add the Workflow File

Create `.github/workflows/sentinel_review.yml` in your repository:

```yaml
name: SentinelPR Auto Code Review

on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write
  issues: write

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - name: Check out repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install SentinelPR
        run: |
          pip install -e .

      - name: Run SentinelPR Automated Review
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          SENTINEL_LLM_PROVIDER: ${{ vars.SENTINEL_LLM_PROVIDER || secrets.SENTINEL_LLM_PROVIDER || '' }}
          SENTINEL_BASE_URL: ${{ vars.SENTINEL_BASE_URL || secrets.SENTINEL_BASE_URL || '' }}
          FAST_MODEL: ${{ vars.FAST_MODEL || secrets.FAST_MODEL || '' }}
          FRONTIER_MODEL: ${{ vars.FRONTIER_MODEL || secrets.FRONTIER_MODEL || '' }}
          DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
        run: |
          python -m sentinel.github
```

#### Step 2: Grant Workflow Permissions

GitHub Actions requires write permissions to publish review comments:
1. In your GitHub repository, go to **Settings** -> **Actions** -> **General**.
2. Scroll to **Workflow permissions**.
3. Select **Read and write permissions**.
4. Check **Allow GitHub Actions to create and approve pull requests**.
5. Click **Save**.

#### Step 3: Add API Keys to Repository Secrets

SentinelPR auto-detects cloud providers based on the secrets present in your repository:
1. Go to **Settings** -> **Secrets and variables** -> **Actions** -> **Secrets** tab.
2. Click **New repository secret** and add your provider key:
   - `DEEPSEEK_API_KEY`: For DeepSeek.
   - `OPENAI_API_KEY`: For OpenAI (`gpt-4o-mini`, `gpt-4o`).
   - `GEMINI_API_KEY`: For Google Gemini (`gemini-2.0-flash`).
3. If no secrets are defined, SentinelPR defaults to deterministic AST heuristics or local Ollama.

#### Step 4: Configure the Two-Tier Model Architecture (Repository Variables)

SentinelPR uses a two-tier model system to optimize latency and cost:
- **`FAST_MODEL`**: Runs high-throughput initial scanning across all changed files, AST symbols, risk analysis, and review summaries.
- **`FRONTIER_MODEL`**: Runs the Adversarial Critic Gate and test synthesis sandbox, conducting deep reasoning only on candidate findings.

To configure models:
1. Go to **Settings** -> **Secrets and variables** -> **Actions** -> **Variables** tab.
2. Click **New repository variable**:

| Variable | Recommended Value (DeepSeek) | Alternative (OpenAI / Gemini) | Role |
| :--- | :--- | :--- | :--- |
| **`FAST_MODEL`** | `deepseek-flash` | `gpt-4o-mini` / `gemini-2.0-flash` | High-speed, cost-efficient pass across entire PR. |
| **`FRONTIER_MODEL`** | `deepseek-v4-pro` | `gpt-4o` / `deepseek-reasoner` | Deep reasoning pass for critic verification & repro test generation. |
| **`SENTINEL_BASE_URL`** | *(Optional)* | Custom proxy URL | For self-hosted gateways, vLLM, or OpenRouter. |

---

## Testing & Benchmarks

SentinelPR includes comprehensive unit tests and a Day-1 synthetic evaluation benchmark suite:

```bash
# Run unit and integration tests
pytest tests/ -v

# Run the synthetic PR benchmark evaluation suite
python -m sentinel.harness.eval_suite
```

The evaluation suite validates the quality gate across five real-world PR archetypes:
* **Mutable Default Bug**: Detects state mutation leak and synthesizes dynamic test proof.
* **Internal Ghost Null-Check**: Identifies redundant checks in domain core and recommends fail-fast simplifications.
* **Perimeter Input Validation**: Accurately preserves mandatory defensive checks on public endpoints (0 false alarms).
* **SQL Injection**: Detects unsafe query formatting at security boundaries.
* **Clean Refactor**: Suppresses false positives on clean code.

---

## Project Structure

```
SentinelPR/
+-- pyproject.toml                         # Project metadata and dependencies
+-- README.md                              # System architecture and usage guide
+-- AGENTS.md                              # Project Constitution (Fail-Fast rules, trust boundaries)
+-- .agents/
|   +-- skills/
|       +-- anti-bloat-auditor/            # Skill: Detecting overprotective code & ghost null-checks
|       +-- test-synthesis-sandbox/        # Skill: Formulating minimal reproduction tests
+-- src/
|   +-- sentinel/
|       +-- config.py                      # Model routing, token budgets, and file filters
|       +-- state.py                       # Pydantic models & LangGraph state with reducers
|       +-- graph.py                       # LangGraph compilation (Fan-out, test loop, critic gate)
|       +-- llm.py                         # Universal client for local (Ollama) & cloud LLMs
|       +-- cli.py                         # Command-line review interface
|       +-- agents/
|       |   +-- triage.py                  # Full-file AST mapper & trust zone classifier
|       |   +-- logic.py                   # Concurrency, state mutations & logic bugs
|       |   +-- security.py                # Injection, secrets & boundary threat analysis
|       |   +-- anti_bloat.py              # Fail-fast auditor for defensive bloat
|       |   +-- test_synthesizer.py        # Minimal test generator with reflection loop
|       |   +-- critic.py                  # Adversarial critic gate (tiered proof standards)
|       |   +-- consolidator.py            # GitHub inline comment & SARIF 2.1.0 formatter
|       +-- harness/
|           +-- sandbox.py                 # Ephemeral isolated test execution harness
|           +-- eval_suite.py              # Synthetic PR benchmark runner
+-- tests/                                 # Pytest test suite (35 test cases across 6 suites)
```

---

## License

This project is licensed under the [MIT License](LICENSE).
