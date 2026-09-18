"""Structured advisory findings; confidence never substitutes for evidence."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Category = Literal["architecture", "redundancy", "performance", "readability", "maintainability", "security"]


class SourceLocation(BaseModel):
    file_path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)

    @model_validator(mode="after")
    def ordered(self):
        if self.end_line < self.start_line:
            raise ValueError("end_line precedes start_line")
        return self


class Evidence(BaseModel):
    kind: Literal["ast", "dependency", "metric", "pattern"]
    description: str
    location: SourceLocation
    source_hash: str


class QualityFinding(BaseModel):
    rule_id: str
    category: Category
    priority: Literal["high", "medium", "low"]
    title: str
    explanation: str
    trigger_conditions: str
    recommendation: str
    subject: str
    fingerprint: str
    evidence: list[Evidence] = Field(min_length=1)
    verification_status: Literal["observed", "hypothesis"]
    confidence: Literal["high", "medium", "low"]
    lifecycle: Literal["new", "existing"] = "new"
    advisory: Literal[True] = True


class BaselineComparison(BaseModel):
    new: int = 0
    existing: int = 0
    resolved: list[str] = Field(default_factory=list)
    unassessed: list[str] = Field(default_factory=list)


class AdviceCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file_path: str
    line: int = Field(ge=1)


class AdviceDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    disposition: Literal["recommend", "keep", "inconclusive"]
    rationale: str = Field(min_length=1, max_length=2000)
    recommendation: str = Field(default="", max_length=2000)
    impact: Literal["high", "medium", "low"] = "low"
    impact_reason: str = Field(default="", max_length=1000)
    benefit: Literal["high", "medium", "low"] = "low"
    benefit_reason: str = Field(default="", max_length=1000)
    confidence: Literal["high", "medium", "low"] = "low"
    evidence: list[AdviceCitation] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def actionable(self):
        if self.disposition == "recommend" and not all(x.strip() for x in (self.recommendation, self.impact_reason, self.benefit_reason)):
            raise ValueError("Recommendations require a specific action and impact/benefit reasons")
        if self.disposition != "recommend" and self.recommendation:
            raise ValueError("Only recommend decisions may prescribe a change")
        return self


class ContextualAdvice(BaseModel):
    fingerprints: list[str]
    subject: str
    status: Literal["reviewed", "unavailable", "insufficient_context", "budget_exhausted"]
    decision: AdviceDecision | None = None
    model: str | None = None
    context_hashes: dict[str, str] = Field(default_factory=dict)
    context_ranges: list[SourceLocation] = Field(default_factory=list)
    limitation: str = ""
    selection_reason: str = ""


class QualityReview(BaseModel):
    snapshot_id: str
    policy_id: str
    analyzed_files: list[str]
    specialists: list[str]
    findings: list[QualityFinding] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    baseline: BaselineComparison | None = None
    unresolved_calls: int = 0
    complete: bool = True
    contextual_advice: list[ContextualAdvice] = Field(default_factory=list)
