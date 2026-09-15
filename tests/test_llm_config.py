import os
from unittest.mock import patch
from sentinel.llm import resolve_llm_credentials


def test_gemini_credential_isolation():
    env = {
        "OPENAI_API_KEY": "sk-openai-should-not-be-used",
        "GEMINI_API_KEY": "sk-gemini-correct-key",
    }
    with patch.dict(os.environ, env, clear=True):
        provider, base_url, api_key, model = resolve_llm_credentials(provider="gemini")
        assert provider == "gemini"
        assert api_key == "sk-gemini-correct-key"
        assert "generativelanguage.googleapis.com" in base_url
        assert "localhost" not in base_url


def test_deepseek_credential_resolution():
    env = {
        "DEEPSEEK_API_KEY": "sk-deepseek-test",
    }
    with patch.dict(os.environ, env, clear=True):
        provider, base_url, api_key, model = resolve_llm_credentials(provider="deepseek")
        assert provider == "deepseek"
        assert api_key == "sk-deepseek-test"
        assert "api.deepseek.com" in base_url
