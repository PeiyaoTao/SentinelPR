# SentinelPR - Autonomous Code Reviewer & PR Quality Gate

SentinelPR is an autonomous multi-agent code reviewer built with **LangGraph**, **Tree-sitter** AST parsing, sandboxed dynamic test verification, and an active **Anti-Bloat Auditor** calibrated by trust zones.

---

## Key Capabilities

1. **Full-File AST Slicing**: Avoids naive parsing of raw diff hunks by parsing full base/head files with Tree-sitter and intersecting diff line spans with AST symbol boundaries.
2. **Trust-Zone Aware Anti-Bloat**: Enforces the **Fail-Fast Principle** by flagging ghost null-checks, redundant validations, and swallowed exceptions in internal domain code without breaking mandatory defensive validations at public perimeters.
3. **Adversarial Critic Gate**: Eliminates false positives by acting as defense counsel for the author, applying a severity-tiered burden of proof before publishing findings.
4. **Sandboxed Test Synthesis**: Generates minimal reproduction tests and executes them in an isolated test harness with a repair reflection loop.
5. **Diff-Hunk Offset Validator**: Accurately differentiates inline diff comments from top-level PR summary comments to prevent GitHub API `422 Unprocessable Entity` errors.
6. **Token-Optimized Architecture**: Uses symbol scope pruning, noise pre-filtering, and model routing (fast models for triage/anti-bloat/consolidation, frontier models for logic/critic) to keep review costs under a few cents per PR.

---

## Architecture Flow

```
                     [Raw Git Diff + Base/Head Files]
                                    │
                          ┌─────────▼─────────┐
                          │   Triage Agent    │ ◄── Noise Filter (Lockfiles, Minified)
                          │  (AST & Boundary) │ ◄── Full-File AST Symbol Slicer
                          └─────────┬─────────┘ ◄── Trust Zone Classifier
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
             ┌──────────────┐┌──────────────┐┌──────────────┐
             │ Logic Agent  ││Security Agent││  Anti-Bloat  │
             │(Concurrency, ││(Taint, Sanit-││   Auditor    │
             │ State, Flaws)││ization, Auth)││ (Trust-Aware)│
             └──────┬───────┘└──────┬───────┘└──────┬───────┘
                    │               │               │
                    └───────────────┼───────────────┘
                                    ▼ (Annotated operator.add)
                    ┌───────────────────────────────┐
                    │     Test Synthesis Loop       │ ◄── 1-2 Repair Retries on Syntax/Import Err
                    │     (Isolated Test Sandbox)   │ ◄── Dynamic Proof for Logic Findings
                    └───────────────┬───────────────┘
                                    ▼
                    ┌───────────────────────────────┐
                    │    Adversarial Critic Gate    │ ◄── Tiered Burden of Proof (Batched)
                    └───────────────┬───────────────┘
                                    ▼
                    ┌───────────────────────────────┐
                    │      Consolidator Agent       │ ◄── Diff Hunk Offset Validator
                    └───────┬───────────────┬───────┘
                            │               │
                    [GitHub Inline/PR]   [SARIF Report]
```

---

## Installation & Setup

```powershell
# Clone or open repository
cd E:\Code_Review_Agent

# Install dependencies
pip install -e ".[dev]"
```

## Running Tests & Benchmarks

```powershell
# Run the automated test suite
pytest tests/ -v

# Run the synthetic PR benchmark evaluation suite
python -m sentinel.harness.eval_suite --run-all
```
