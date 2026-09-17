"""Validation outcomes are separate from advisory review findings."""
from typing import Literal
from pydantic import BaseModel, Field

CheckName = Literal["lint", "types", "tests", "build", "dependencies", "secrets"]
CHECK_NAMES = ("lint", "types", "tests", "build", "dependencies", "secrets")

class CheckIssue(BaseModel):
    rule: str
    message: str
    path: str | None = None
    line: int | None = None

class CheckResult(BaseModel):
    name: CheckName
    status: Literal["passed", "failed", "incomplete", "error"]
    summary: str
    issues: list[CheckIssue] = Field(default_factory=list)

class ValidationReport(BaseModel):
    results: list[CheckResult] = Field(default_factory=list)
    snapshot_id: str
