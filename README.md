# SentinelPR: Autonomous Code Reviewer & PR Quality Gate

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![LangGraph](https://img.shields.io/badge/Orchestration-LangGraph-orange.svg)](https://github.com/langchain-ai/langgraph)
[![Tree-sitter](https://img.shields.io/badge/AST-Tree--sitter-green.svg)](https://tree-sitter.github.io/)

SentinelPR is a production-grade multi-agent code reviewer built with LangGraph, Tree-sitter AST parsing, sandboxed test verification with an automated repair loop, an active Anti-Bloat / Fail-Fast Auditor calibrated by trust boundaries, an adversarial critic gate, and a diff-hunk offset validator.

---

## Key Capabilities

1. **Full-File AST Slicing**: Slices post-change files into full AST syntax trees rather than naive diff hunks, isolating enclosing function/class boundaries and imports for high-precision token efficiency.
2. **Trust-Zone Aware Anti-Bloat**: Enforces the **Fail-Fast Principle** by flagging ghost null-checks, redundant validations, and swallowed exceptions in internal domain code without breaking mandatory defensive validations at public perimeter boundaries.
3. **Adversarial Critic Gate**: Acts as defense counsel for the author to eliminate false alarms and nitpicks, applying a severity-tiered standard of proof before publishing findings.
4. **Sandboxed Test Synthesis**: Formulates minimal standalone pytest scripts for candidate logic findings and executes them in an isolated test harness with a 1-retry reflection repair loop.
5. **Diff-Hunk Offset Validator**: Accurately maps candidate finding line numbers against git patch hunks to route inline comments appropriately and eliminate GitHub API 422 Unprocessable Entity errors.
6. **Token-Optimized Architecture**: Prunes surrounding source context down to changed symbol scopes, pre-filters noisy files (lockfiles, minified code, assets), and routes tasks across model tiers to keep typical PR review costs at a few cents.

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
+-- tests/                                 # Pytest test suite (18 test cases)
```

---

## License

This project is licensed under the [MIT License](LICENSE).
