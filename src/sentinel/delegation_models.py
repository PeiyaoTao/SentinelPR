"""External opinions are separate from evidence-gated code findings."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExternalCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    excerpt_id: str
    line: int = Field(ge=1)


class ExternalFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    category: Literal["logic", "security", "architecture", "maintainability", "performance", "readability", "redundancy"]
    priority: Literal["high", "medium", "low"]
    claim: str = Field(min_length=1, max_length=2000)
    recommendation: str = Field(min_length=1, max_length=2000)
    evidence: list[ExternalCitation] = Field(min_length=1, max_length=10)


class DelegatedReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    package_id: str
    reviewer: str = Field(min_length=1, max_length=200)
    reviewed_excerpts: list[str] = Field(max_length=500)
    findings: list[ExternalFinding] = Field(max_length=30)
    limitations: list[str] = Field(max_length=30)

    @model_validator(mode="after")
    def unique_reviewed(self):
        if len(self.reviewed_excerpts) != len(set(self.reviewed_excerpts)):
            raise ValueError("Reviewed excerpt IDs must be unique")
        if any(len(item) > 2000 for item in self.limitations):
            raise ValueError("Limitations must be at most 2000 characters")
        return self
