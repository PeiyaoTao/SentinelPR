# SentinelPR Project Constitution (AGENTS.md)

## Core Mission
SentinelPR is an autonomous PR quality gate and code review system. Its objective is to provide high-precision, low-noise reviews by detecting genuine logic errors, concurrency flaws, security boundaries, and overprotective "defensive bloat," while rigorously eliminating false positives through an adversarial critic gate and sandboxed reproduction tests.

---

## The Fail-Fast Principle

1. **Explicit Over Implicit Failure**:
   Code should fail immediately, visibly, and predictably when preconditions or internal invariants are violated.
2. **Prohibition of Silent Swallowing**:
   Never catch broad exceptions (`except Exception: pass`, `try {} catch (e) {}`) without re-raising or converting them to domain-specific fatal errors.
3. **No Sentinel Value Abuse**:
   Internal methods must not return magic error codes or `None`/`null` as pseudo-exceptions unless `Optional`/`None` is the explicit semantic contract of the method.

---

## The Trust Boundary Matrix

Every code symbol analyzed belongs to one of three trust zones. Anti-bloat and defensive programming rules are strictly governed by this classification:

| Trust Zone | Scope & Examples | Defensive Rules & Auditor Policy |
| :--- | :--- | :--- |
| **`PERIMETER`** | Public HTTP/REST/gRPC handlers, CLI entry points, raw input deserializers, DB query inputs. | **Defensive checks are MANDATORY.** Strict validation, sanitization, schema parsing, and boundary error handling must be present. Anti-bloat auditor must **never** flag validation at the perimeter. |
| **`INTERNAL_CORE`** | Domain services, internal helper functions, private class methods, typed internal contracts. | **Fail-Fast and Anti-Bloat are ENFORCED.** Flag ghost null-checks, redundant validations on already-validated models, and paranoid `try...except` blocks. If types/preconditions guarantee an invariant, trust it. |
| **`INTER_MODULE`** | Boundaries between decoupled subsystems (e.g. storage layer interface, external SDK clients). | Assertions and contract validation are permitted, but fallback defaults must not mask systemic misconfigurations. |

---

## Agent Operational Standards

1. **Triage Agent**:
   - Ingests full base and head source files, not just raw diff hunks.
   - Slices AST around changed line ranges to isolate enclosing symbols.
   - Drops non-logic files (lockfiles, assets, minified code) before invoking LLM agents.
2. **Logic & Concurrency Agent**:
   - Identifies race conditions, state mutation leaks, edge cases, off-by-one errors.
   - Formulates concrete proof hypotheses for reproducible bugs.
3. **Security Agent**:
   - Focuses strictly on boundary threat vectors (taint flow, auth/authz, injection, secret leaks).
   - Bypassed when changes are purely internal or cosmetic to conserve tokens.
4. **Anti-Bloat Auditor**:
   - Respects the Trust Boundary Matrix.
   - Recommends clean, idiomatic simplifications and elimination of ghost checks in `INTERNAL_CORE`.
5. **Test Synthesis & Sandbox**:
   - Generates minimal standalone reproduction scripts.
   - Runs tests in an isolated, network-disabled environment.
   - Retries once if errors are environment/syntax setup glitches (`ENV_SETUP_ERROR`).
6. **Adversarial Critic Gate**:
   - Defense counsel for the author.
   - Tiered standard of proof: Critical bugs require disproof of impossibility to reject; low-severity/anti-bloat suggestions require strong justification.
7. **Consolidator Agent**:
   - Matches candidate line numbers against diff hunk offsets to guarantee valid GitHub inline comments (preventing 422 errors).
   - Outputs both GitHub PR comments and SARIF 2.1.0 JSON.
