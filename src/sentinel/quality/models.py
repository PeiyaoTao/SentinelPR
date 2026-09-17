"""Structured advisory findings; confidence never substitutes for evidence."""

from typing import Literal
from pydantic import BaseModel, Field, model_validator

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
