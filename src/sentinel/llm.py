"""
Universal LLM client adapter supporting local models (Ollama, vLLM, LMStudio)
and cloud providers (OpenAI, Gemini, DeepSeek, Anthropic) via OpenAI-compatible endpoints.
"""

import os
from typing import Any, Dict, List, Optional
import requests

from sentinel.config import default_config


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
        self.provider = provider or os.getenv("SENTINEL_LLM_PROVIDER", default_config.provider).lower()
        self.base_url = base_url or os.getenv("SENTINEL_BASE_URL", default_config.base_url)
        self.api_key = (
            api_key
            or os.getenv("SENTINEL_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("DEEPSEEK_API_KEY")
            or os.getenv("GEMINI_API_KEY")
            or default_config.api_key
        )
        self.model = model or default_config.fast_model
        self.temperature = temperature if temperature is not None else default_config.temperature

        # Adjust base URL for known providers if needed
        if self.provider == "deepseek" and "localhost" in self.base_url:
            self.base_url = "https://api.deepseek.com/v1"
        elif self.provider == "openai" and "localhost" in self.base_url:
            self.base_url = "https://api.openai.com/v1"

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
