"""
Universal LLM client adapter supporting local models (Ollama, vLLM, LMStudio)
and cloud providers (OpenAI, Gemini, DeepSeek, Anthropic) via OpenAI-compatible endpoints.
"""

import os
from typing import Any, Dict, List, Optional, Tuple
import json
import hashlib
from pathlib import Path
import subprocess
import sys
import time

from sentinel.llm_budget import active_budget

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
        stage: str = "model",
    ):
        p, u, k, m = resolve_llm_credentials(provider, base_url, api_key, model)
        self.stage = stage
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

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload: Dict[str, Any] = {
            "model": self.model, "messages": messages, "temperature": self.temperature,
            "max_tokens": default_config.llm_max_output_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        endpoint = f"{self.base_url.rstrip('/')}/chat/completions"
        budget = active_budget.get()
        record: dict[str, Any] = {"stage": self.stage, "model": self.model, "status": "started", "elapsed_seconds": 0, "usage": None}
        if budget:
            budget.calls.append(record)
            budget.pending_cache.pop(self.stage, None)
        started = time.monotonic()
        try:
            cached = self._cache_path(endpoint, payload)
            if cached and cached.exists() and time.time() - cached.stat().st_mtime < 86400:
                data = json.loads(cached.read_text(encoding="utf-8"))
                content = self._content(data)
                record["status"] = "cached"
                if budget:
                    budget.pending_cache[self.stage] = cached
                print(f"SentinelPR LLM [{self.stage}]: reused cached response ({self.model})", flush=True)
                return content
            timeout = float(default_config.llm_timeout_seconds)
            if budget:
                timeout = min(timeout, budget.remaining_seconds())
                remaining = default_config.llm_review_output_tokens - budget.reserved_tokens
                if timeout <= 0 or remaining <= 0:
                    record["status"] = "budget_exhausted"
                    raise RuntimeError("Shared LLM review budget exhausted")
                payload["max_tokens"] = min(payload["max_tokens"], remaining)
                # Reserve the full cap: failures can consume tokens without usage data.
                budget.reserved_tokens += payload["max_tokens"]
            record["output_token_cap"] = payload["max_tokens"]
            print(f"SentinelPR LLM [{self.stage}]: starting {self.model}; deadline {timeout:.0f}s, output cap {payload['max_tokens']}", flush=True)
            request = {"endpoint": endpoint, "headers": headers, "payload": payload, "timeout": timeout}
            process = subprocess.run([sys.executable, "-m", "sentinel.llm_transport"],
                                     input=json.dumps(request), capture_output=True, text=True,
                                     encoding="utf-8", timeout=timeout, check=True)
            data = json.loads(process.stdout)
            content = self._content(data)
            usage = data.get("usage")
            if isinstance(usage, dict):
                record["usage"] = {key: usage[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                                   if isinstance(usage.get(key), int) and usage[key] >= 0}
            record["status"] = "completed"
            # Reduced-budget responses are not reused as full-budget answers.
            if cached and payload["max_tokens"] == default_config.llm_max_output_tokens:
                cached.parent.mkdir(parents=True, exist_ok=True)
                import tempfile
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=cached.parent, delete=False) as temp:
                    json.dump(data, temp)
                    temporary = Path(temp.name)
                temporary.replace(cached)
                if budget:
                    budget.pending_cache[self.stage] = cached
            return content
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError, IndexError, RuntimeError) as error:
            if record["status"] != "budget_exhausted":
                record["status"] = "timeout" if isinstance(error, subprocess.TimeoutExpired) else "failed"
            if budget:
                budget.incomplete = True
            raise RuntimeError(f"LLM request {record['status']} ({type(error).__name__}); no complete response available") from error
        finally:
            record["elapsed_seconds"] = round(time.monotonic() - started, 3)
            print(f"SentinelPR LLM [{self.stage}]: {record['status']} after {record['elapsed_seconds']}s; usage={record['usage']}", flush=True)

    @staticmethod
    def _content(data):
        if "transport_error" in data:
            raise RuntimeError("Provider request failed")
        choice = data["choices"][0]
        if choice.get("finish_reason") != "stop":
            raise ValueError("Incomplete or unsupported completion finish reason")
        content = choice["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Empty model response")
        return content

    def _cache_path(self, endpoint, payload):
        if not default_config.llm_cache_dir:
            return None
        # All reviewer Python changes invalidate the cache. Prompts contain the
        # exact selected code/context; no fuzzy matching or line-number reuse.
        root = Path(__file__).parent
        implementation = [(str(p.relative_to(root)), p.read_text(encoding="utf-8")) for p in sorted(root.rglob("*.py"))]
        budget = active_budget.get()
        policy = default_config.model_dump(exclude={"api_key", "llm_cache_dir"})
        key = hashlib.sha256(json.dumps([endpoint, payload, implementation, policy, budget.snapshot if budget else ""], sort_keys=True).encode()).hexdigest()
        return Path(default_config.llm_cache_dir) / (key + ".json")


def get_llm_client(tier: str = "fast", stage: str = "model") -> LLMClient:
    """Helper to get either fast or frontier model client."""
    model = default_config.frontier_model if tier == "frontier" else default_config.fast_model
    return LLMClient(model=model, stage=stage)
