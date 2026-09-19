# Configuration

[Back to README](../README.md) · [GitHub variables](github-actions.md) · [Model evaluation](development.md#comparing-advice-models)

Configuration lives in [config.py](../src/sentinel/config.py); endpoint and credential resolution live in [llm.py](../src/sentinel/llm.py). Environment settings are loaded when the process imports SentinelPR. There is no user configuration YAML loader.

## Providers and model roles

The CLI accepts `heuristics`, `ollama`, `deepseek`, `openai`, and `gemini`. An explicit `SENTINEL_LLM_PROVIDER` selects the provider; otherwise provider-specific keys are detected in this order: DeepSeek, OpenAI, Gemini. Without a selection or provider key, the default is `heuristics`.

The current optional critic, contextual quality reviewer, and repository project assessor use **`FRONTIER_MODEL`**. Scanning, risk metrics, reproduction templates, and PR executive summaries are deterministic. `FAST_MODEL` remains available in configuration and report labels, but no current review stage calls the fast tier. Model labels in a report do not demonstrate that both tiers ran.

Use a model identifier supported by your endpoint. Built-in names are implementation defaults, not a recommendation or guarantee of current provider availability. The adapter expects an OpenAI-compatible chat-completions endpoint and requests JSON output for structured model decisions.

| Environment variable | Purpose |
| --- | --- |
| `SENTINEL_LLM_PROVIDER` | Explicit provider selection; `heuristics` makes no model calls |
| `DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` | Provider-specific credentials |
| `SENTINEL_API_KEY` | Generic credential override for local processes; also set the provider explicitly |
| `SENTINEL_BASE_URL` | API base URL, including `/v1` where required by the endpoint |
| `FRONTIER_MODEL` | Model used by the optional review stages |
| `FAST_MODEL` | Retained fast-tier configuration and report label |

Keep credentials in your shell environment or CI secret store. SentinelPR does not automatically load a `.env` file. Selected source excerpts are sent to the configured model endpoint.

For PowerShell, with the provider key already supplied securely:

```powershell
$env:SENTINEL_LLM_PROVIDER = 'deepseek'
$env:FRONTIER_MODEL = 'YOUR_SUPPORTED_MODEL'
python -m sentinel.cli --repo . --markdown review.md
```

Replace the model placeholder before running. In Bash, set the same variables with `export`. CLI `--model` sets both configured model names. Use one consistent provider/base-URL selection: environment values are also consulted by the client, so clear conflicting overrides when changing CLI settings.

## Model-call controls

| Stage | Default maximum calls | Context budget | Disable |
| --- | --- | --- | --- |
| Code-finding critic | 8 | 12,000 characters of serialized excerpts; instructions/candidate metadata are additional | `--no-llm-critic` or `SENTINEL_LLM_CRITIC=false` |
| Contextual quality advice | 5 | 18,000 characters of serialized observations/excerpts; system instructions are additional | `--no-llm-quality` or `SENTINEL_LLM_QUALITY=false` |
| Repository project assessment | 1 | 48,000 characters of serialized project context; system instructions are additional | Select `heuristics` to disable all model stages |

Stage budgets allow up to 13 calls in PR mode and 14 in repository mode, but shared time/output budgets can stop model work earlier. Static analysis and executable validation continue. Security/correctness candidates are prioritized before lower-severity advice.

| Environment variable | Default | Scope |
| --- | --- | --- |
| `SENTINEL_LLM_TIMEOUT_SECONDS` | `180` | Hard deadline for each request worker, including provider keepalives |
| `SENTINEL_LLM_REVIEW_SECONDS` | `600` | Wall-clock window from review start for model requests; excludes subsequent executable validation |
| `SENTINEL_LLM_MAX_OUTPUT_TOKENS` | `8192` | Provider `max_tokens` per response |
| `SENTINEL_LLM_REVIEW_OUTPUT_TOKENS` | `65536` | Shared output allowance; each attempted call reserves its full cap, including failed requests |
| `SENTINEL_LLM_CACHE_DIR` | Empty (disabled) | Optional persistent directory for exact-context response reuse |

Deadlines terminate the local HTTP worker. They cannot guarantee the provider immediately stops remote generation or billing. Output limits do not cover input tokens or guarantee a monetary cost; reasoning-token accounting depends on the endpoint. Use reported usage to tune these limits, especially for reasoning models. A deeper review can increase these values and `SENTINEL_QUALITY_MAX_GROUPS` explicitly.

Each request logs its stage, deadline, completion status, duration and numeric provider-reported usage. JSON/SARIF retain the accounting; missing usage remains unavailable. Timeout, shared-budget exhaustion, truncation or invalid model output prevents an otherwise CLEAN review from being reported complete. Existing blocking findings retain precedence. Per-stage selection budgets still disclose unassessed observations separately.

Cache entries expire after 24 hours. Reuse requires matching endpoint, model, parameters, exact prompt/excerpts, reviewer implementation, configuration and supplied source snapshot (Python files for PR review, all collected files for repository review). This permits repeated documentation-only PR revisions to reuse unchanged code analysis. Cached responses still undergo normal schema/citation validation. Use a trusted cache directory: entries contain model responses and may contain source excerpts or sensitive findings. Do not let target code or untrusted contributors write it. Failed/incomplete transports are not cached. Contextual schema/citation rejection during a review also removes that response from the cache.

`SENTINEL_QUALITY_MAX_GROUPS` changes the quality call budget; `0` prevents calls. `SENTINEL_QUALITY_CONTEXT_CHARS` changes its context budget and must be at least `1000`. Boolean switches accept `true` or `false` case-insensitively. Invalid values fail configuration loading.

Other limits can be set through the Python API before invoking a graph:

```python
from sentinel.config import default_config

# Critic budget and timeout
default_config.llm_critic_max_findings = 8
default_config.llm_critic_context_chars = 12000
default_config.llm_timeout_seconds = 180

# Static specialist policy
default_config.quality_max_function_lines = 80
default_config.quality_max_nesting = 4
default_config.quality_max_complexity = 10
default_config.quality_duplicate_min_statements = 6
default_config.quality_max_findings = 200
default_config.quality_include_tests = False
default_config.quality_forbidden_dependencies = {"app.domain": ["app.api"]}
```

Tests are indexed for relationships but excluded from specialist advice by default. Hitting the static finding limit makes static review incomplete. Changing the static specialist policy requires an explicitly refreshed [baseline](usage.md#repository-quality-baselines).

## Repository collection limits

| Python configuration field | Default |
| --- | --- |
| `repository_max_files` | 500 source/context files |
| `repository_max_file_bytes` | 256,000 bytes per file |
| `repository_max_total_bytes` | 4,000,000 bytes total |
| `repository_llm_context_chars` | 48,000 characters |

These limits apply to repository analysis. Executable validation and Git blob collection have separate snapshot limits; see [validation](validation.md). Not every legacy field in `SentinelConfig` is enforced by every entry point; the controls above describe the active collection and review paths.
