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
        default=180,
        description="Timeout in seconds for LLM generation requests (useful for large local models).",
    )

    # Token & PR Budgets
    max_pr_churn_lines: int = Field(
        default=1500,
        description="Maximum total lines of diff to process before applying symbol prioritization.",
    )
    max_symbols_per_file: int = Field(
        default=25,
        description="Limit on AST symbol scopes analyzed per changed file.",
    )

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
        cfg.api_key = deepseek_key
        cfg.base_url = "https://api.deepseek.com/v1"
        cfg.fast_model = os.getenv("FAST_MODEL", "deepseek-chat")
        cfg.frontier_model = os.getenv("FRONTIER_MODEL", "deepseek-chat")
    elif openai_key:
        cfg.provider = "openai"
        cfg.api_key = openai_key
        cfg.base_url = "https://api.openai.com/v1"
        cfg.fast_model = os.getenv("FAST_MODEL", "gpt-4o-mini")
        cfg.frontier_model = os.getenv("FRONTIER_MODEL", "gpt-4o")
    elif gemini_key:
        cfg.provider = "gemini"
        cfg.api_key = gemini_key
        cfg.fast_model = os.getenv("FAST_MODEL", "gemini-2.0-flash")
        cfg.frontier_model = os.getenv("FRONTIER_MODEL", "gemini-2.0-flash")

    if os.getenv("SENTINEL_BASE_URL"):
        cfg.base_url = os.getenv("SENTINEL_BASE_URL")
    if os.getenv("FAST_MODEL"):
        cfg.fast_model = os.getenv("FAST_MODEL")
    if os.getenv("FRONTIER_MODEL"):
        cfg.frontier_model = os.getenv("FRONTIER_MODEL")

    return cfg


# Singleton default config instance initialized from environment
default_config = load_config_from_env()
