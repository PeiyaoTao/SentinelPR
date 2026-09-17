"""
Universal LLM client adapter supporting local models (Ollama, vLLM, LMStudio)
and cloud providers (OpenAI, Gemini, DeepSeek, Anthropic) via OpenAI-compatible endpoints.
"""

import os
from typing import Any, Dict, List, Optional, Tuple
import requests

from sentinel.config import default_config


def resolve_llm_credentials(
    provider: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> Tuple[str, str, str, str]:
    """
    Consolidates provider, endpoint, model, and credentials atomically.
    Prevents cross-provider credential contamination (e.g. Gemini selecting OpenAI key).
    """
    resolved_provider = (provider or os.getenv("SENTINEL_LLM_PROVIDER") or default_config.provider).lower()

    provider_endpoints = {
        "deepseek": "https://api.deepseek.com/v1",
        "openai": "https://api.openai.com/v1",
        "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
        "ollama": "http://localhost:11434/v1",
    }

    # Dedicated key lookup bound strictly to the active provider
    if api_key:
        resolved_key = api_key
    elif os.getenv("SENTINEL_API_KEY"):
        resolved_key = os.environ["SENTINEL_API_KEY"]
    elif resolved_provider == "deepseek":
        resolved_key = os.getenv("DEEPSEEK_API_KEY", default_config.api_key)
    elif resolved_provider == "openai":
        resolved_key = os.getenv("OPENAI_API_KEY", default_config.api_key)
    elif resolved_provider == "gemini":
        resolved_key = os.getenv("GEMINI_API_KEY", default_config.api_key)
    else:
        resolved_key = default_config.api_key

    # Resolve base URL
    if base_url:
        resolved_base_url = base_url
    elif os.getenv("SENTINEL_BASE_URL"):
        resolved_base_url = os.environ["SENTINEL_BASE_URL"]
    elif resolved_provider in provider_endpoints and ("localhost" in default_config.base_url or resolved_provider != default_config.provider):
        resolved_base_url = provider_endpoints[resolved_provider]
    else:
        resolved_base_url = default_config.base_url

    resolved_model = model or default_config.fast_model
    return resolved_provider, resolved_base_url, resolved_key, resolved_model


class LLMClient:
    """Universal LLM client supporting local Ollama endpoints and cloud APIs."""

    def __init__(
        self,
        provider: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ):
        p, u, k, m = resolve_llm_credentials(provider, base_url, api_key, model)
        self.provider = p
        self.base_url = u
        self.api_key = k
        self.model = m
        self.temperature = temperature if temperature is not None else default_config.temperature

    def complete(self, messages: List[Dict[str, str]], json_mode: bool = False) -> str:
        """
        Sends chat completion request to the configured LLM endpoint.
        Returns the raw string response from the model.
        """
        if self.provider == "heuristics":
            return ""

        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }

        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        endpoint = f"{self.base_url.rstrip('/')}/chat/completions"

        try:
            response = requests.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=default_config.llm_timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except requests.exceptions.RequestException as e:
            # If endpoint fails or unreachable, surface informative error
            raise RuntimeError(
                f"Failed to connect to LLM provider '{self.provider}' at '{endpoint}': {str(e)}\n"
                f"Make sure Ollama or your LLM server is running, or check your API key."
            ) from e


def get_llm_client(tier: str = "fast") -> LLMClient:
    """Helper to get either fast or frontier model client."""
    model = default_config.frontier_model if tier == "frontier" else default_config.fast_model
    return LLMClient(model=model)
