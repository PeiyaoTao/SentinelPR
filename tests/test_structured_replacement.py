from sentinel.agents.consolidator import consolidator_agent_node
from sentinel.state import (
    DiffHunk,
    ExactCodeReplacement,
    Finding,
    FindingCategory,
    PRReviewState,
    ReviewOutcome,
    Severity,
    TrustZone,
)


def test_structured_replacement_valid_syntax_emits_suggestion():
    hunk = DiffHunk(
        file_path="app.py",
        old_start=1,
        old_lines=3,
        new_start=1,
        new_lines=3,
        content="@@ -1,3 +1,3 @@\n def foo():\n-    x = 1\n+    x = 2\n     return x",
    )
    finding = Finding(
        id="FIND-1",
        category=FindingCategory.LOGIC,
        severity=Severity.HIGH,
        file_path="app.py",
        start_line=2,
        end_line=2,
        title="Incorrect value",
        explanation="x should be 3",
        exact_replacement=ExactCodeReplacement(
            file_path="app.py",
            revision="HEAD",
            start_line=2,
            end_line=2,
            replacement_text="    x = 3",
        ),
    )
    state: PRReviewState = {
        "diff": "",
        "base_files": {},
        "head_files": {"app.py": "def foo():\n    x = 2\n    return x\n"},
        "changed_files": ["app.py"],
        "hunks": [hunk],
        "symbols": [],
        "candidate_findings": [finding],
        "repro_tests": {},
        "verified_findings": [finding],
        "consolidated_report": None,
    }

    result = consolidator_agent_node(state)
    report = result["consolidated_report"]
    assert len(report.inline_comments) == 1
    assert "```suggestion\n    x = 3\n```" in report.inline_comments[0]["body"]
    assert report.review_outcome == ReviewOutcome.CHANGES_REQUIRED


def test_structured_replacement_invalid_syntax_falls_back_to_text():
    hunk = DiffHunk(
        file_path="app.py",
        old_start=1,
        old_lines=3,
        new_start=1,
        new_lines=3,
        content="@@ -1,3 +1,3 @@\n def foo():\n-    x = 1\n+    x = 2\n     return x",
    )
    # The replacement is English prose, which corrupts syntax if put in suggestion
    finding = Finding(
        id="FIND-2",
        category=FindingCategory.ANTI_BLOAT,
        severity=Severity.HIGH,
        file_path="app.py",
        start_line=2,
        end_line=2,
        title="Bad syntax replacement",
        explanation="Explain",
        exact_replacement=ExactCodeReplacement(
            file_path="app.py",
            revision="HEAD",
            start_line=2,
            end_line=2,
            replacement_text="Use proper variable initialization here",
        ),
    )
    state: PRReviewState = {
        "diff": "",
        "base_files": {},
        "head_files": {"app.py": "def foo():\n    x = 2\n    return x\n"},
        "changed_files": ["app.py"],
        "hunks": [hunk],
        "symbols": [],
        "candidate_findings": [finding],
        "repro_tests": {},
        "verified_findings": [finding],
        "consolidated_report": None,
    }

    result = consolidator_agent_node(state)
    report = result["consolidated_report"]
    assert len(report.inline_comments) == 1
    # Must NOT contain ```suggestion
    assert "```suggestion" not in report.inline_comments[0]["body"]
    assert "**Suggested Fix**:" in report.inline_comments[0]["body"]


def test_review_outcome_states():
    # 1. Clean run
    clean_state: PRReviewState = {
        "diff": "",
        "base_files": {},
        "head_files": {},
        "changed_files": [],
        "hunks": [],
        "symbols": [],
        "candidate_findings": [],
        "repro_tests": {},
        "verified_findings": [],
        "uninspected_files": [],
        "consolidated_report": None,
    }
    clean_res = consolidator_agent_node(clean_state)
    assert clean_res["consolidated_report"].review_outcome == ReviewOutcome.CLEAN

    # 2. Incomplete analysis
    incomplete_state: PRReviewState = {
        "diff": "",
        "base_files": {},
        "head_files": {},
        "changed_files": ["large_file.py"],
        "hunks": [],
        "symbols": [],
        "candidate_findings": [],
        "repro_tests": {},
        "verified_findings": [],
        "uninspected_files": ["large_file.py"],
        "consolidated_report": None,
    }
    inc_res = consolidator_agent_node(incomplete_state)
    assert inc_res["consolidated_report"].review_outcome == ReviewOutcome.INCOMPLETE_REVIEW
    assert "Incomplete Analysis" in inc_res["consolidated_report"].summary_markdown
