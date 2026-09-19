"""
Configuration and settings for SentinelPR.
"""

from typing import List
from pydantic import BaseModel, Field


class SentinelConfig(BaseModel):
    """System-wide configuration for LLMs, sandboxing, and token control."""

    # Model & Provider Configuration
    provider: str = Field(
        default="heuristics",
        description="LLM provider: 'heuristics' (offline AST rules), 'ollama' (local), 'openai', 'gemini', 'deepseek'.",
    )
    base_url: str = Field(
        default="http://localhost:11434/v1",
        description="API base URL (defaults to Ollama's OpenAI-compatible endpoint).",
    )
    api_key: str = Field(
        default="",
        description="API key for cloud providers (or set OPENAI_API_KEY, GEMINI_API_KEY, DEEPSEEK_API_KEY).",
    )
    fast_model: str = Field(
        default="qwen2.5-coder:7b",
        description="Fast/cost-effective model for triage, anti-bloat, and consolidator.",
    )
    frontier_model: str = Field(
        default="qwen2.5-coder:7b",
        description="High-reasoning model for logic, security, and the critic gate.",
    )
    temperature: float = Field(
        default=0.1,
        description="Sampling temperature for LLM review consistency.",
    )
    llm_timeout_seconds: int = Field(
        default=180, gt=0,
        description="Timeout in seconds for LLM generation requests (useful for large local models).",
    )

    llm_review_seconds: int = Field(default=600, gt=0)
    llm_max_output_tokens: int = Field(default=8192, gt=0)
    llm_review_output_tokens: int = Field(default=65536, gt=0)
    llm_cache_dir: str = ""

    # Optional contextual criticism; model decisions never establish proof.
    llm_critic_enabled: bool = True
    llm_critic_max_findings: int = Field(default=8, ge=0)
    llm_critic_context_chars: int = Field(default=12000, ge=1000)

    # Contextual advice has a separate budget and never changes code verdicts.
    llm_quality_enabled: bool = True
    llm_quality_max_groups: int = Field(default=5, ge=0)
    llm_quality_context_chars: int = Field(default=18000, ge=1000)

    # Token & PR Budgets
    max_pr_churn_lines: int = Field(
        default=1500,
        description="Maximum total lines of diff to process before applying symbol prioritization.",
    )
    max_symbols_per_file: int = Field(
        default=25,
        description="Limit on AST symbol scopes analyzed per changed file.",
    )

    # Repository review budgets (skipped files are disclosed in the report).
    repository_max_files: int = Field(default=500, gt=0)
    repository_max_file_bytes: int = Field(default=256_000, gt=0)
    repository_max_total_bytes: int = Field(default=4_000_000, gt=0)
    repository_llm_context_chars: int = Field(default=48_000, ge=1000)

    # Advisory specialist policies. No target code/configuration is executed.
    quality_include_tests: bool = False
    quality_max_function_lines: int = Field(default=80, ge=1)
    quality_max_nesting: int = Field(default=4, ge=1)
    quality_max_complexity: int = Field(default=10, ge=1)
    quality_duplicate_min_statements: int = Field(default=6, ge=2)
    quality_max_findings: int = Field(default=200, ge=1)
    quality_forbidden_dependencies: dict[str, list[str]] = Field(default_factory=dict)

    # Sandboxing & Test Verification
    sandbox_timeout_seconds: int = Field(
        default=5,
        description="Execution timeout for dynamic reproduction test scripts.",
    )
    max_test_repair_attempts: int = Field(
        default=1,
        description="Number of reflection retries if test runner encounters ENV_SETUP_ERROR.",
    )
    use_docker: bool = Field(
        default=False,
        description="Whether to run tests in Docker container (recommended for production CI).",
    )

    # Noise Pre-Filter Patterns (Files to ignore from LLM review)
    ignored_file_patterns: List[str] = Field(
        default=[
            "package-lock.json",
            "yarn.lock",
            "pnpm-lock.yaml",
            "poetry.lock",
            "Pipfile.lock",
            "Cargo.lock",
            "composer.lock",
            "*.min.js",
            "*.min.css",
            "*.map",
            "*.svg",
            "*.png",
            "*.jpg",
            "*.jpeg",
            "*.gif",
            "*.ico",
            "*.pdf",
            "*.pb.go",
            "*_pb2.py",
            "*.proto",
            "*.sql",  # DB auto-dumps/migrations often handled by dedicated linters
        ]
    )


def load_config_from_env() -> SentinelConfig:
    import os
    cfg = SentinelConfig()
    provider = os.getenv("SENTINEL_LLM_PROVIDER")
    deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    gemini_key = os.getenv("GEMINI_API_KEY")

    if provider:
        cfg.provider = provider.lower()
    elif deepseek_key:
        cfg.provider = "deepseek"
    elif openai_key:
        cfg.provider = "openai"
    elif gemini_key:
        cfg.provider = "gemini"

    # Set provider-specific defaults
    if cfg.provider == "deepseek":
        cfg.api_key = deepseek_key or (os.getenv("SENTINEL_API_KEY") or "")
        cfg.base_url = "https://api.deepseek.com/v1"
        cfg.fast_model = "deepseek-chat"
        cfg.frontier_model = "deepseek-chat"
    elif cfg.provider == "openai":
        cfg.api_key = openai_key or (os.getenv("SENTINEL_API_KEY") or "")
        cfg.base_url = "https://api.openai.com/v1"
        cfg.fast_model = "gpt-4o-mini"
        cfg.frontier_model = "gpt-4o"
    elif cfg.provider == "gemini":
        cfg.api_key = gemini_key or (os.getenv("SENTINEL_API_KEY") or "")
        cfg.fast_model = "gemini-2.0-flash"
        cfg.frontier_model = "gemini-2.0-flash"

    critic_setting = os.getenv("SENTINEL_LLM_CRITIC")
    if critic_setting is not None:
        if critic_setting.lower() not in {"true", "false"}:
            raise ValueError("SENTINEL_LLM_CRITIC must be true or false")
        cfg.llm_critic_enabled = critic_setting.lower() == "true"

    quality_setting = os.getenv("SENTINEL_LLM_QUALITY")
    if quality_setting is not None:
        if quality_setting.lower() not in {"true", "false"}:
            raise ValueError("SENTINEL_LLM_QUALITY must be true or false")
        cfg.llm_quality_enabled = quality_setting.lower() == "true"
    for env, field in (("SENTINEL_QUALITY_MAX_GROUPS", "llm_quality_max_groups"),
                       ("SENTINEL_QUALITY_CONTEXT_CHARS", "llm_quality_context_chars")):
        if env in os.environ:
            values = cfg.model_dump()
            values[field] = int(os.environ[env])
            cfg = SentinelConfig.model_validate(values)

    for env, field in (("SENTINEL_LLM_TIMEOUT_SECONDS", "llm_timeout_seconds"),
                       ("SENTINEL_LLM_REVIEW_SECONDS", "llm_review_seconds"),
                       ("SENTINEL_LLM_MAX_OUTPUT_TOKENS", "llm_max_output_tokens"),
                       ("SENTINEL_LLM_REVIEW_OUTPUT_TOKENS", "llm_review_output_tokens")):
        if env in os.environ:
            values = cfg.model_dump()
            values[field] = int(os.environ[env])
            cfg = SentinelConfig.model_validate(values)
    cfg.llm_cache_dir = os.getenv("SENTINEL_LLM_CACHE_DIR", "")

    # Explicit environment overrides always take precedence
    if os.getenv("SENTINEL_API_KEY"):
        cfg.api_key = os.environ["SENTINEL_API_KEY"]
    if os.getenv("SENTINEL_BASE_URL"):
        cfg.base_url = os.environ["SENTINEL_BASE_URL"]
    if os.getenv("FAST_MODEL"):
        cfg.fast_model = os.environ["FAST_MODEL"]
    if os.getenv("FRONTIER_MODEL"):
        cfg.frontier_model = os.environ["FRONTIER_MODEL"]

    return cfg


# Singleton default config instance initialized from environment
default_config = load_config_from_env()
