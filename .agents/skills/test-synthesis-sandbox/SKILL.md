---
name: test-synthesis-sandbox
description: Skill for synthesizing minimal, standalone reproduction tests and classifying sandbox verification outcomes.
---

# Test Synthesis & Sandbox Skill

## Purpose
Produce self-contained pytest test cases that demonstrate a reported logic or concurrency defect in changed code without requiring the entire external test suite or heavy fixtures.

## Synthesis Guidelines

1. **Self-Contained Imports**:
   - Mock all network, database, and filesystem calls using `unittest.mock` or pytest fixtures.
   - Avoid importing production configuration files that require live environment variables.

2. **Targeted Assertion**:
   - The test must assert the *expected correct behavior*.
   - A bug is successfully reproduced when the test execution fails with an assertion error or exception matching the hypothesized defect (`REPRODUCED_DYNAMICALLY`).
   - If the test passes, the defect hypothesis is invalidated (`NOT_REPRODUCED`).

3. **Status Classification**:
   - `REPRODUCED_DYNAMICALLY`: Test ran, exercised target code, and failed as expected on the bug.
   - `NOT_REPRODUCED`: Test ran successfully to completion without error; hypothesis disproved.
   - `ENV_SETUP_ERROR`: Test failed to start due to missing package, syntax error, or unmocked external resource. Triggers 1 repair iteration.
