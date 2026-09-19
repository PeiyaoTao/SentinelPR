# Understanding reports

[Back to README](../README.md) · [Implemented rules](architecture.md) · [Validation](validation.md)

Read the outcome, scope gaps, and validation status first. The executive summary is generated from recorded findings and checks. Attaching validation refreshes it; a previous model summary cannot substitute for tool results.

## GitHub summary and full evidence

The GitHub review contains the outcome, validation status, up to three optional improvements, and coverage/audit counts. Its workflow link leads to the full `sentinel-pr-review` artifact. Metric inventories, KEEP explanations, repeated source evidence and the complete critic audit stay in Markdown/JSON/SARIF exports. Metrics on the same symbol share evidence and conditions in the Markdown inventory.

Location-specific code findings remain inline, with critic details collapsed. On later revisions, SentinelPR updates its marked bot comments when their anchors remain current and creates new comments for outdated anchors. After a completed review, absent findings are labelled no longer retained; this is not proof they were fixed. Incomplete reviews do not retire old findings. Older comments without SentinelPR markers are left untouched.

The secret critic rejects the known synthetic `abcdefghijklmnop1234` fixture only when embedded as Python source in a test string. It records the rejection and skips the model call. Ordinary credential assignments, unknown values and AWS-shaped keys in tests remain candidates. A static pattern match does not establish that a credential is live.

## Outcomes and exit codes

| Outcome | Exit code | Meaning |
| --- | --- | --- |
| `CLEAN` | 0 | No blocking findings or failed checks within the supported review scope |
| `CHANGES_REQUIRED` | 1 | A retained HIGH/CRITICAL code finding or failed validation check |
| `INCOMPLETE_REVIEW` | 2 | Relevant analysis or validation could not complete |
| `INFRASTRUCTURE_FAILURE` | 3 | Infrastructure/tool error prevents a reliable completed run |

When attaching validation, precedence is infrastructure failure, changes required, incomplete review, then clean. Existing findings and inspection gaps remain in the report. Empty PR diffs exit without generating a report; a stale GitHub revision also exits with code 2.

`CLEAN` is not a production-readiness guarantee. The [GitHub publication policy](github-actions.md#publication-and-outcomes) can still issue an automatic approval when a clean report has no retained code findings.

## Code findings and critic decisions

Severity describes possible impact; proof status describes the recorded evidence. Untested or inconclusive HIGH/CRITICAL candidates are downgraded to nonblocking hypotheses. A syntactic global mutation alone does not establish a race. Pattern-based static verification labels should be interpreted within the individual rule's scope.

The critic can retain, reject, or downgrade candidates. Its optional model must cite supplied source lines and cannot promote a hypothesis into proof. A model challenge to a verified blocker is recorded for independent adjudication instead of automatically removing it.

The **Critic decision audit** retains one record per candidate, including:

- Original claim, location, rule, and severity.
- Deterministic decision and reasoning.
- Model status, opinion, reasoning, and cited source hashes when available.
- Final decision, severity, duplicate suppression, and unavailable/budget-limited model review.

A report with two candidates and zero retained findings therefore has an explanation trail. Valid citations establish that the referenced source was supplied; they do not prove the model's reasoning is correct.

## Specialist observations and contextual advice

The six static specialists report source patterns and metrics. Their observations are advisory SARIF notes. Confidence in a measured structure does not establish confidence that refactoring will help.

Selected groups receive contextual model review with one of three dispositions:

| Disposition | Interpretation |
| --- | --- |
| `recommend` | A specific action with cited rationale and reasons for estimated impact and benefit |
| `keep` | The implementation is judged reasonable in the supplied context |
| `inconclusive` | Available evidence does not justify an action |

Model calls are selected by rule priority, known importing/calling files, lifecycle, and overlapping signals. Suggested actions are ranked by model-estimated impact, confidence, then benefit. Alphabetical order only breaks remaining ties. These qualitative estimates are not measured engineering outcomes.

Keep/inconclusive decisions remain visible in the inventory and exports. When model review is disabled, unavailable, or out of budget, static prompts are labeled as unassessed. The static observations and baseline fingerprints are preserved in all cases.

## Scope and metrics

| Report field | What it establishes |
| --- | --- |
| Review effort | A heuristic based on churn, complexity, public symbols, and changed test files; not defect severity |
| Changed-scope complexity sum | Sum of scope scores; nested scopes can overlap. It is not a base/head delta or unique-branch count. |
| Test files changed | At least one matching test file changed; not relevance, execution, or coverage |
| Measured test coverage | Currently unavailable |
| Unresolved calls | Limits of static call resolution; not a count of defects |
| Complete within supported scope | Static analysis completed within its supported scope/budgets; not exhaustive model or semantic review |
| Snapshot identifier | Identifies the input to that analysis/check stage; quality and validation can use different file sets |

A passing test check means pytest completed successfully on the validation snapshot. Dependency auditing covers the supplied pins; secret scanning covers supported patterns in the current snapshot. None implies complete architectural, authorization, or runtime-performance analysis.

## Export formats

- **Markdown:** summary, findings, contextual advice, critic audit, and validation details. Local PR terminal output is shorter; export Markdown for the full audit.
- **JSON:** the structured Pydantic report, available through `report.model_dump_json()` and GitHub PR artifacts. `critic_audit` stores candidate decisions; `quality_review.contextual_advice` stores quality decisions.
- **SARIF 2.1.0:** code findings plus advisory specialist notes; validation adds a separate run. Critic audit is run metadata, not rejected code-scanning alerts. Quality results retain fingerprints, static rule prompts, and contextual decision properties.

GitHub inline comments are anchored to eligible diff lines. Out-of-hunk observations remain in the summary. Suggested replacement syntax is checked before rendering a suggestion block; this does not establish behavioral correctness or guarantee every API publication succeeds.
