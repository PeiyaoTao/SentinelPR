"""Per-review model accounting, shared across graph tasks via ContextVar."""
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
import time
import hashlib
import json
from pathlib import Path

from sentinel.config import default_config


@dataclass
class ReviewBudget:
    started: float = field(default_factory=time.monotonic)
    calls: list[dict] = field(default_factory=list)
    reserved_tokens: int = 0
    incomplete: bool = False
    snapshot: str = ""
    pending_cache: dict[str, Path] = field(default_factory=dict)

    def remaining_seconds(self):
        return default_config.llm_review_seconds - (time.monotonic() - self.started)


active_budget: ContextVar[ReviewBudget | None] = ContextVar("review_budget", default=None)


def set_review_snapshot(files):
    budget = active_budget.get()
    if budget is not None:
        budget.snapshot = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def invalid_model_response(stage):
    """Callers use this when schema/citation checks reject a completed response."""
    budget = active_budget.get()
    if budget is not None:
        budget.incomplete = True
        for record in reversed(budget.calls):
            if record["stage"] == stage:
                if record["status"] in {"completed", "cached"}:
                    record["status"] = "invalid_response"
                    cached = budget.pending_cache.pop(stage, None)
                    if cached is not None:
                        cached.unlink(missing_ok=True)
                break


def bounded_review(function):
    @wraps(function)
    def run(*args, **kwargs):
        from sentinel.checks.report import refresh_executive_summary
        from sentinel.state import ReviewOutcome
        budget = ReviewBudget()
        token = active_budget.set(budget)
        try:
            result = function(*args, **kwargs)
            report = result["consolidated_report"]
            report.llm_usage = budget.calls
            if budget.incomplete and report.review_outcome == ReviewOutcome.CLEAN:
                report.review_outcome = ReviewOutcome.INCOMPLETE_REVIEW
                result["review_outcome"] = report.review_outcome
                report.summary_markdown = report.summary_markdown.replace("**Status**: CLEAN", "**Status**: INCOMPLETE_REVIEW").replace("**Outcome:** `CLEAN`", "**Outcome:** `INCOMPLETE_REVIEW`")
            if budget.calls:
                completed = sum(c["status"] in {"completed", "cached"} for c in budget.calls)
                report.summary_markdown += f"\n### Model execution\n\n{completed}/{len(budget.calls)} requests completed or reused. See review.json for per-request timing and reported token usage.\n"
                if budget.incomplete:
                    report.summary_markdown += "Some model work timed out, failed, or exceeded the shared budget; contextual coverage is incomplete.\n"
                report.sarif_json["runs"][0].setdefault("properties", {})["llmUsage"] = budget.calls
            refresh_executive_summary(report)
            return result
        finally:
            active_budget.reset(token)
    return run
