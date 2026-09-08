"""
Tests for Consolidator Agent: Diff hunk offset validation, 422 error prevention, and SARIF output.
"""

from sentinel.agents.consolidator import consolidator_agent_node, generate_sarif, get_hunk_line_ranges
from sentinel.state import (
    DiffHunk,
    Finding,
    FindingCategory,
    PRReviewState,
    Severity,
    TrustZone,
)


def test_hunk_line_ranges():
    hunk = DiffHunk(
        file_path="app.py",
        old_start=10,
        old_lines=3,
        new_start=10,
        new_lines=4,
        content="@@ -10,3 +10,4 @@\n context line 1\n+added line 2\n context line 3\n context line 4",
    )
    ranges = get_hunk_line_ranges([hunk])

    assert "app.py" in ranges
    assert 10 in ranges["app.py"]
    assert 11 in ranges["app.py"]
    assert 12 in ranges["app.py"]
    assert 13 in ranges["app.py"]
    assert 99 not in ranges["app.py"]


def test_diff_offset_validation_prevents_422():
    hunk = DiffHunk(
        file_path="app.py",
        old_start=10,
        old_lines=2,
        new_start=10,
        new_lines=2,
        content="@@ -10,2 +10,2 @@\n+line 10\n+line 11",
    )
    # Finding 1 is inside the hunk (line 11)
    finding_inside = Finding(
        id="FIND-1",
        category=FindingCategory.LOGIC,
        severity=Severity.HIGH,
        file_path="app.py",
        start_line=10,
        end_line=11,
        title="Inside Hunk Bug",
        explanation="...",
    )
    # Finding 2 is outside the hunk (line 85)
    finding_outside = Finding(
        id="FIND-2",
        category=FindingCategory.SECURITY,
        severity=Severity.MEDIUM,
        file_path="app.py",
        start_line=85,
        end_line=85,
        title="Outside Hunk Bug",
        explanation="...",
    )

    state: PRReviewState = {
        "diff": "",
        "base_files": {},
        "head_files": {},
        "changed_files": ["app.py"],
        "hunks": [hunk],
        "symbols": [],
        "candidate_findings": [finding_inside, finding_outside],
        "repro_tests": {},
        "verified_findings": [finding_inside, finding_outside],
        "consolidated_report": None,
    }

    result = consolidator_agent_node(state)
    report = result["consolidated_report"]

    assert len(report.inline_comments) == 1
    assert report.inline_comments[0]["line"] == 11
    assert report.inline_comments[0]["finding_id"] == "FIND-1"

    assert len(report.out_of_hunk_notes) == 1
    assert report.out_of_hunk_notes[0]["line"] == 85
    assert report.out_of_hunk_notes[0]["finding_id"] == "FIND-2"


def test_generate_sarif():
    finding = Finding(
        id="SEC-01",
        category=FindingCategory.SECURITY,
        severity=Severity.CRITICAL,
        file_path="auth.py",
        start_line=5,
        end_line=5,
        title="SQL Injection",
        explanation="Concatenated SQL",
    )
    sarif = generate_sarif([finding])

    assert sarif["version"] == "2.1.0"
    assert len(sarif["runs"]) == 1
    run = sarif["runs"][0]
    assert run["tool"]["driver"]["name"] == "SentinelPR"
    assert len(run["results"]) == 1
    assert run["results"][0]["level"] == "error"
    assert run["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "auth.py"
