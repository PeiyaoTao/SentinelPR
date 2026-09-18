"""Versioned, policy-bound baselines for repository quality findings."""

import os
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal
from pydantic import BaseModel
from sentinel.quality.models import BaselineComparison, QualityReview


class BaselineEntry(BaseModel):
    fingerprint: str
    files: list[str]


class QualityBaseline(BaseModel):
    version: Literal[1] = 1
    root: str
    policy_id: str
    findings: list[BaselineEntry]


def save_baseline(report, path: str) -> None:
    if report.repository_inventory is None or report.quality_review is None:
        raise ValueError("Quality baselines require a repository review")
    review = report.quality_review
    if not review.complete:
        raise ValueError("Cannot replace a baseline with an incomplete quality review")
    baseline = QualityBaseline(root=os.path.normcase(report.repository_inventory.root), policy_id=review.policy_id,
        findings=[BaselineEntry(fingerprint=f.fingerprint,
            files=sorted({e.location.file_path for e in f.evidence})) for f in review.findings])
    Path(path).write_text(baseline.model_dump_json(indent=2), encoding="utf-8")


def compare_baseline(review: QualityReview, inventory, path: str) -> None:
    baseline = QualityBaseline.model_validate_json(Path(path).read_text(encoding="utf-8"))
    if baseline.root != os.path.normcase(inventory.root):
        raise ValueError("Baseline belongs to a different repository directory")
    if baseline.policy_id != review.policy_id:
        raise ValueError("Baseline uses a different specialist policy; create a new baseline explicitly")
    for entry in baseline.findings:
        for name in entry.files:
            if PurePosixPath(name).is_absolute() or PureWindowsPath(name).drive or ".." in PurePosixPath(name.replace("\\", "/")).parts:
                raise ValueError("Baseline source paths must stay inside the repository")
    previous = {f.fingerprint: f for f in baseline.findings}
    current = {f.fingerprint for f in review.findings}
    comparison = BaselineComparison()
    for finding in review.findings:
        if finding.fingerprint in previous:
            finding.lifecycle = "existing"
            comparison.existing += 1
        else:
            comparison.new += 1
    analyzed = set(review.analyzed_files)
    inventory_paths = set(inventory.files)
    for fingerprint in sorted(set(previous) - current):
        # A rule did not necessarily disappear if its source was skipped, excluded or capped.
        covered = review.complete and all(
            p in analyzed or (p not in inventory_paths and not os.path.lexists(Path(inventory.root) / p))
            for p in previous[fingerprint].files
        )
        (comparison.resolved if covered else comparison.unassessed).append(fingerprint)
    review.baseline = comparison
