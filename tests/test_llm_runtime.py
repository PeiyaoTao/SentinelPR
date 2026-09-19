"""Transport limits, conservative accounting, exact-response reuse and disclosure."""
import json
import subprocess
import sys
import time
from types import SimpleNamespace
import pytest
from sentinel.config import default_config, load_config_from_env
from sentinel.llm import LLMClient
from sentinel.llm_budget import ReviewBudget, active_budget, bounded_review
from sentinel.state import ConsolidatedReport, ReviewOutcome


def response(content='{"ok": true}', reason="stop"):
    return {"choices": [{"finish_reason": reason, "message": {"content": content}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}


@pytest.fixture
def budget(monkeypatch):
    monkeypatch.setattr(default_config, "llm_cache_dir", "")
    monkeypatch.setattr(default_config, "llm_review_seconds", 10)
    monkeypatch.setattr(default_config, "llm_max_output_tokens", 100)
    monkeypatch.setattr(default_config, "llm_review_output_tokens", 100)
    value = ReviewBudget()
    token = active_budget.set(value)
    yield value
    active_budget.reset(token)


def client():
    return LLMClient(provider="ollama", base_url="http://localhost:11434/v1", stage="critic")


def test_shared_output_budget_prevents_additional_transport(monkeypatch, budget):
    requests = []
    def run(*args, **kwargs):
        requests.append(json.loads(kwargs["input"]))
        return SimpleNamespace(stdout=json.dumps(response()))
    monkeypatch.setattr("sentinel.llm.subprocess.run", run)
    assert client().complete([]) == '{"ok": true}'
    with pytest.raises(RuntimeError, match="budget_exhausted"):
        client().complete([])
    assert len(requests) == 1
    assert requests[0]["payload"]["max_tokens"] == 100
    assert budget.incomplete
    assert budget.calls[0]["usage"]["total_tokens"] == 120
    assert budget.calls[0]["stage"] == "critic"


def test_real_process_keepalive_cannot_extend_deadline(monkeypatch, budget):
    # Substitute a slow transport that emits regular output, exercising actual
    # subprocess termination without a provider or network connection.
    monkeypatch.setattr(default_config, "llm_timeout_seconds", .2)
    real_run = subprocess.run
    def keepalive(*args, **kwargs):
        return real_run([sys.executable, "-c", "import time; [(print(' ', flush=True), time.sleep(.02)) for _ in range(500)]"],
                        capture_output=True, text=True, timeout=kwargs["timeout"])
    monkeypatch.setattr("sentinel.llm.subprocess.run", keepalive)
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="timeout"):
        client().complete([])
    assert time.monotonic() - started < 5
    assert budget.calls[0]["status"] == "timeout"
    assert budget.incomplete


@pytest.mark.parametrize("reason", ["length", "content_filter", None])
def test_truncated_or_filtered_output_not_accepted(monkeypatch, budget, reason):
    monkeypatch.setattr("sentinel.llm.subprocess.run", lambda *a, **k: SimpleNamespace(stdout=json.dumps(response(reason=reason))))
    with pytest.raises(RuntimeError):
        client().complete([])
    assert budget.incomplete


def test_cache_reuses_exact_prompt_but_changed_context_calls_provider(monkeypatch, budget, tmp_path):
    monkeypatch.setattr(default_config, "llm_cache_dir", str(tmp_path))
    monkeypatch.setattr(default_config, "llm_review_output_tokens", 1000)
    calls = []
    monkeypatch.setattr("sentinel.llm.subprocess.run", lambda *a, **k: calls.append(k) or SimpleNamespace(stdout=json.dumps(response())))
    model = client()
    prompt = [{"role": "user", "content": "def old(): pass"}]
    model.complete(prompt)
    model.complete(prompt)
    model.complete([{"role": "user", "content": "def new(): pass"}])
    assert len(calls) == 2
    assert [c["status"] for c in budget.calls] == ["completed", "cached", "completed"]
    model.model = "different-model"
    model.complete(prompt)
    assert len(calls) == 3
    assert "Authorization" not in "".join(p.read_text() for p in tmp_path.iterdir())


def test_expired_review_stops_before_transport(monkeypatch, budget):
    budget.started -= 20
    monkeypatch.setattr("sentinel.llm.subprocess.run", lambda *a, **k: pytest.fail("Expired review called provider"))
    with pytest.raises(RuntimeError, match="budget_exhausted"):
        client().complete([])


def test_partial_model_work_never_becomes_clean_and_budget_resets(monkeypatch):
    @bounded_review
    def review():
        budget = active_budget.get()
        assert budget.calls == []
        budget.incomplete = True
        budget.calls.append({"status": "timeout"})
        return {"consolidated_report": ConsolidatedReport(summary_markdown="# Review", sarif_json={"runs": [{}]})}
    for _ in range(2):
        result = review()
        assert result["review_outcome"] == ReviewOutcome.INCOMPLETE_REVIEW
        assert "contextual coverage is incomplete" in result["consolidated_report"].summary_markdown
    assert active_budget.get() is None


def test_invalid_environment_budget_fails_fast(monkeypatch):
    monkeypatch.setenv("SENTINEL_LLM_REVIEW_SECONDS", "0")
    with pytest.raises(ValueError):
        load_config_from_env()



def test_invalid_contextual_answer_evicts_cache_and_marks_incomplete(monkeypatch, budget, tmp_path):
    from sentinel.llm_budget import invalid_model_response
    monkeypatch.setattr(default_config, "llm_cache_dir", str(tmp_path))
    monkeypatch.setattr("sentinel.llm.subprocess.run", lambda *a, **k: SimpleNamespace(stdout=json.dumps(response())))
    client().complete([])
    assert list(tmp_path.iterdir())
    invalid_model_response("critic")
    assert list(tmp_path.iterdir()) == []
    assert budget.incomplete and budget.calls[0]["status"] == "invalid_response"


def test_supplied_snapshot_change_invalidates_cache(monkeypatch, budget, tmp_path):
    from sentinel.llm_budget import set_review_snapshot
    monkeypatch.setattr(default_config, "llm_cache_dir", str(tmp_path))
    monkeypatch.setattr(default_config, "llm_review_output_tokens", 1000)
    calls = []
    monkeypatch.setattr("sentinel.llm.subprocess.run", lambda *a, **k: calls.append(k) or SimpleNamespace(stdout=json.dumps(response())))
    set_review_snapshot({"caller.py": "old"})
    client().complete([])
    set_review_snapshot({"caller.py": "new"})
    client().complete([])
    assert len(calls) == 2



def test_truncated_response_keeps_usage_and_safe_reason(monkeypatch, budget, capsys):
    monkeypatch.setattr("sentinel.llm.subprocess.run", lambda *a, **k: SimpleNamespace(stdout=json.dumps(response(content="private source", reason="length"))))
    with pytest.raises(RuntimeError, match="finish_length"):
        client().complete([])
    assert budget.calls[0]["usage"]["total_tokens"] == 120
    assert budget.calls[0]["error_code"] == "finish_length"
    output = capsys.readouterr().out
    assert "finish_length" in output
    assert "private source" not in output


@pytest.mark.parametrize("data,code", [
    ({"transport_error": "HTTPError", "http_status": 429}, "http_429"),
    ({"transport_error": "ReadTimeout"}, "ReadTimeout"),
    ({"transport_error": "private provider body"}, "transport_error"),
    ([], "invalid_response_shape"),
])
def test_safe_transport_failure_codes(monkeypatch, budget, capsys, data, code):
    monkeypatch.setattr("sentinel.llm.subprocess.run", lambda *a, **k: SimpleNamespace(stdout=json.dumps(data)))
    with pytest.raises(RuntimeError, match=code):
        client().complete([])
    assert budget.calls[0]["error_code"] == code
    assert "private provider body" not in capsys.readouterr().out


def test_worker_preserves_http_status_without_body(monkeypatch, capsys):
    import io
    import requests
    from sentinel import llm_transport
    response = requests.Response()
    response.status_code = 429
    response._content = b"private provider body"
    def post(*args, **kwargs):
        raise requests.HTTPError("sensitive URL", response=response)
    monkeypatch.setattr(llm_transport.requests, "post", post)
    monkeypatch.setattr(llm_transport.sys, "stdin", io.StringIO(json.dumps({"endpoint": "unused", "payload": {}, "headers": {}, "timeout": 1})))
    llm_transport.main()
    assert json.loads(capsys.readouterr().out) == {"transport_error": "HTTPError", "http_status": 429}
