"""Evidence, safe counterexamples, scoping and end-to-end specialist regressions."""

import difflib
import json
import pytest

from sentinel.config import SentinelConfig, default_config
from sentinel.graph import review_pr, review_repository
from sentinel.quality.analyzers import SPECIALISTS
from sentinel.quality.baseline import save_baseline
from sentinel.quality.index import RepositoryIndex
from sentinel.quality.pipeline import analyze_quality, verify_evidence
from sentinel.state import ReviewOutcome


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(default_config, "provider", "heuristics")
    monkeypatch.setenv("SENTINEL_LLM_PROVIDER", "heuristics")


def analyze(files, **policy):
    index = RepositoryIndex(files)
    return index, analyze_quality(index, SentinelConfig(**policy))


def write(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def patch(before, after, name="core.py"):
    return f"diff --git a/{name} b/{name}\n" + "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), fromfile=f"a/{name}", tofile=f"b/{name}"))


def test_index_cross_file_calls_relative_imports_and_tests():
    index = RepositoryIndex({
        "src/pkg/__init__.py": "",
        "src/pkg/math.py": "def plus(a, b): return a + b\n",
        "src/pkg/service.py": "from .math import plus as add\ndef run(): return add(1, 2)\n",
        "tests/test_math.py": "from pkg.math import plus\ndef test_plus(): assert plus(1, 2) == 3\n",
    })
    plus = next(s for s in index.functions() if s.name == "plus")
    assert {s.name for s in index.get_callers(plus.id)} == {"run", "test_plus"}
    run = next(s for s in index.functions() if s.name == "run")
    assert index.get_callees(run.id) == [plus]
    assert index.get_related_tests(plus.id) == ["tests/test_math.py"]
    assert index.get_module_dependencies("src/pkg/service.py") == ["src/pkg/math.py"]
    assert index.get_source("src/pkg/math.py", 1, 1).startswith("def plus")
    with pytest.raises(ValueError):
        index.get_source("src/pkg/math.py", 0, 1)


def test_index_does_not_resolve_shadowed_or_nested_bindings():
    index = RepositoryIndex({"core.py": "def helper(): return 1\ndef parameter(helper): return helper()\ndef nested():\n    def helper(): return 2\n    return helper()\n"})
    helper = next(s for s in index.functions() if s.qualified_name == "helper")
    assert index.get_callers(helper.id) == []
    assert index.unresolved_calls == 2


def test_index_reports_invalid_and_ambiguous_modules_without_execution():
    index = RepositoryIndex({"core.py": "raise RuntimeError('not executed')\n", "src/core.py": "value = 1\n", "invalid.py": "def invalid(\n"})
    assert "core" not in index.modules
    assert index.limitations
    assert "invalid.py" in index.errors


def test_architecture_cycle_has_a_witness_and_acyclic_code_is_quiet():
    _, findings = analyze({"a.py": "import b\n", "b.py": "import a\n"})
    cycle = next(f for f in findings if f.rule_id == "architecture.import-cycle")
    assert {e.location.file_path for e in cycle.evidence} == {"a.py", "b.py"}
    assert cycle.verification_status == "observed"
    _, safe = analyze({"a.py": "import b\n", "b.py": "value = 1\n"})
    assert not safe


def test_type_checking_and_lazy_imports_do_not_make_definite_cycles():
    _, findings = analyze({"a.py": "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import b\n", "b.py": "import a\n"})
    assert not findings
    _, findings = analyze({"a.py": "def lazy():\n    import b\n", "b.py": "import a\n"})
    assert not findings


def test_explicit_layer_rule_and_prefix_boundary():
    _, findings = analyze({"app/domain.py": "import app.api\n", "app/api.py": "value = 1\n"}, quality_forbidden_dependencies={"app.domain": ["app.api"]})
    assert any(f.rule_id == "architecture.forbidden-import" for f in findings)
    _, findings = analyze({"app/domain_extra.py": "import app.api\n", "app/api.py": "value = 1\n"}, quality_forbidden_dependencies={"app.domain": ["app.api"]})
    assert not findings


def test_duplicate_functions_require_substantial_matching_bodies():
    body = "    a = value + 1\n    b = a * 2\n    c = b - 3\n    d = c / 4\n    e = d + 5\n    return e\n"
    _, findings = analyze({"a.py": "def first(value):\n" + body, "b.py": "def second(value):\n" + body})
    duplicate = next(f for f in findings if f.rule_id == "redundancy.duplicate-function")
    assert len(duplicate.evidence) == 2
    _, safe = analyze({"a.py": "def first(): return 1\n", "b.py": "def second(): return 1\n"})
    assert not safe


def test_unreachable_statement_and_conditional_return_counterexample():
    _, findings = analyze({"core.py": "def dead():\n    return 1\n    print('unreachable')\n"})
    assert findings[0].rule_id == "redundancy.unreachable"
    assert findings[0].evidence[0].location.start_line == 3
    _, safe = analyze({"core.py": "def live(flag):\n    if flag:\n        return 1\n    return 2\n"})
    assert not safe


def test_readability_and_maintainability_have_separate_measured_evidence():
    source = "def check(a, b):\n    if a:\n        if b:\n            return 1\n    return 0\n"
    _, findings = analyze({"core.py": source}, quality_max_function_lines=3, quality_max_nesting=1, quality_max_complexity=2)
    assert {f.rule_id for f in findings} == {"readability.long-function", "readability.deep-nesting", "maintainability.branch-complexity"}
    assert all(f.advisory and f.verification_status == "observed" for f in findings)


def test_test_code_excluded_unless_explicitly_requested():
    source = "def test_one():\n    return 1\n    print('unreachable')\n"
    assert not analyze({"tests/test_one.py": source})[1]
    assert analyze({"tests/test_one.py": source}, quality_include_tests=True)[1]


def test_performance_queries_and_constant_regex_are_hypotheses():
    source = "import re\ndef run(items, cursor):\n    for item in items:\n        re.compile('abc')\n        cursor.execute(item)\n"
    _, findings = analyze({"core.py": source})
    assert {f.rule_id for f in findings} == {"performance.regex-in-loop", "performance.query-in-loop"}
    assert all(f.verification_status == "hypothesis" for f in findings)


def test_performance_skips_nonloop_and_deferred_function_calls():
    source = "import re\ndef run(items, cursor):\n    pattern = re.compile('abc')\n    cursor.execute('select 1')\n    for item in items:\n        def deferred():\n            cursor.execute(item)\n"
    assert not analyze({"core.py": source})[1]


def test_regex_receiver_shadow_and_import_binding_scopes():
    source = "import re\ndef shadow(re, items):\n    for item in items:\n        re.compile('abc')\ndef local():\n    re = 1\ndef actual(items):\n    for item in items:\n        re.compile('abc')\n"
    _, findings = analyze({"core.py": source})
    regex = [f for f in findings if f.rule_id == "performance.regex-in-loop"]
    assert len(regex) == 1
    assert "actual" in regex[0].subject


def test_security_local_parameter_path_and_safe_counterexamples():
    source = "import subprocess\ndef execute(command):\n    subprocess.run(command, shell=True)\n"
    _, findings = analyze({"core.py": source})
    finding = next(f for f in findings if f.category == "security")
    assert finding.verification_status == "hypothesis"
    assert "attacker" in finding.trigger_conditions
    for code in ["def safe(): return eval('1+1')\n", "def safe(value):\n    value = '1+1'\n    return eval(value)\n", "def eval(value): return value\ndef safe(value): return eval(value)\n"]:
        assert not analyze({"core.py": code})[1]


def test_evidence_gate_rejects_stale_hash_and_bad_location():
    index, findings = analyze({"core.py": "def f():\n    return 1\n    print('dead')\n"})
    finding = findings[0]
    assert verify_evidence(index, finding)
    altered = finding.model_copy(deep=True)
    altered.evidence[0].source_hash = "not-the-snapshot"
    assert not verify_evidence(index, altered)
    altered = finding.model_copy(deep=True)
    altered.evidence[0].location.end_line = 100
    assert not verify_evidence(index, altered)


def test_fingerprints_survive_unrelated_line_insertions():
    text = "def f():\n    return 1\n    print('dead')\n"
    assert analyze({"core.py": text})[1][0].fingerprint == analyze({"core.py": "# header\n" + text})[1][0].fingerprint


def test_pr_existing_quality_issue_suppressed_and_new_one_reported(monkeypatch):
    monkeypatch.setattr(default_config, "quality_max_function_lines", 2)
    base = "def f():\n    x = 1\n    return x\n"
    head = "def f():\n    x = 2\n    return x\n"
    result = review_pr(patch(base, head), {"core.py": head}, {"core.py": base})
    assert not result["quality_review"].findings
    short = "def f(): return 1\n"
    result = review_pr(patch(short, head), {"core.py": head}, {"core.py": short})
    assert any(f.rule_id == "readability.long-function" for f in result["quality_review"].findings)
    assert "Specialist code-quality review" in result["consolidated_report"].summary_markdown
    assert result["consolidated_report"].review_outcome == ReviewOutcome.CLEAN


def test_pr_unrelated_unchanged_file_does_not_generate_quality_findings(monkeypatch):
    monkeypatch.setattr(default_config, "quality_max_function_lines", 2)
    head = {"core.py": "value = 2\n", "unchanged.py": "def f():\n    x = 1\n    return x\n"}
    result = review_pr(patch("value = 1\n", head["core.py"]), head)
    assert not result["quality_review"].findings


def test_repository_quality_is_advisory_and_exports_sarif(tmp_path):
    write(tmp_path, "core.py", "def f():\n    return 1\n    print('dead')\n")
    report = review_repository(tmp_path)["consolidated_report"]
    assert report.review_outcome == ReviewOutcome.CLEAN
    assert report.quality_review.findings
    sarif = report.sarif_json["runs"][0]["results"]
    assert sarif[0]["ruleId"] == "redundancy.unreachable"
    assert sarif[0]["properties"]["advisory"] is True
    assert sarif[0]["level"] == "note"


def test_baseline_new_existing_resolved_and_unassessed(tmp_path):
    source = "def f():\n    return 1\n    print('dead')\n"
    path = write(tmp_path, "core.py", source)
    baseline = tmp_path / "quality-baseline.json"
    initial = review_repository(tmp_path)["consolidated_report"]
    save_baseline(initial, baseline)
    repeated = review_repository(tmp_path, baseline)["quality_review"]
    assert repeated.baseline.existing == 1
    assert repeated.baseline.new == 0
    path.write_text("def invalid(\n")
    incomplete = review_repository(tmp_path, baseline)["quality_review"]
    assert not incomplete.baseline.resolved
    assert len(incomplete.baseline.unassessed) == 1
    path.write_text("def f(): return 1\n")
    fixed = review_repository(tmp_path, baseline)["quality_review"]
    assert len(fixed.baseline.resolved) == 1
    path.write_text(source + "\ndef other():\n    return 2\n    print('dead again')\n")
    added = review_repository(tmp_path, baseline)["quality_review"]
    assert added.baseline.existing == 1
    assert added.baseline.new == 1


def test_baseline_rejects_policy_mismatch_and_incomplete_replacement(tmp_path, monkeypatch):
    write(tmp_path, "core.py", "def f(): return 1\n")
    baseline = tmp_path / "baseline.json"
    save_baseline(review_repository(tmp_path)["consolidated_report"], baseline)
    original = baseline.read_text()
    monkeypatch.setattr(default_config, "quality_max_complexity", 11)
    with pytest.raises(ValueError, match="different specialist policy"):
        review_repository(tmp_path, baseline)
    write(tmp_path, "bad.py", "def invalid(\n")
    with pytest.raises(ValueError, match="incomplete"):
        save_baseline(review_repository(tmp_path)["consolidated_report"], baseline)
    assert baseline.read_text() == original


def test_capped_quality_review_is_incomplete(tmp_path, monkeypatch):
    monkeypatch.setattr(default_config, "quality_max_findings", 1)
    monkeypatch.setattr(default_config, "quality_max_function_lines", 2)
    write(tmp_path, "core.py", "def f():\n    return 1\n    print('dead')\n")
    report = review_repository(tmp_path)["consolidated_report"]
    assert report.review_outcome == ReviewOutcome.INCOMPLETE_REVIEW
    assert not report.quality_review.complete
    assert "Finding budget reached" in report.summary_markdown


def test_context_targets_deep_findings_instead_of_only_file_prefixes(tmp_path):
    from sentinel.agents.project import _project_context
    source = "# filler that should not dominate model context\n" * 200 + "def important():\n    return 1\n    print('unreachable')\n"
    write(tmp_path, "core.py", source)
    state = review_repository(tmp_path)
    payload, included = _project_context(state, 5000)
    assert "def important" in json.loads(payload)["source_excerpts"]["core.py"]
    assert len(payload) <= 5000


def test_specialists_all_have_registry_entries():
    assert set(SPECIALISTS) == {"architecture", "redundancy", "performance", "readability", "maintainability", "security"}


def test_root_module_named_src_is_indexed():
    index = RepositoryIndex({"src.py": "def f(): return 1\n"})
    assert index.modules == {"src": "src.py"}


def test_cli_saves_and_compares_baseline(tmp_path, monkeypatch, capsys):
    from sentinel import cli
    write(tmp_path, "core.py", "def f():\n    return 1\n    print('dead')\n")
    baseline = tmp_path / "baseline.json"
    monkeypatch.setattr("sys.argv", ["sentinel", "--repo", str(tmp_path), "--save-baseline", str(baseline)])
    with pytest.raises(SystemExit) as exit_status:
        cli.main()
    assert exit_status.value.code == 0
    assert baseline.exists()
    capsys.readouterr()
    monkeypatch.setattr("sys.argv", ["sentinel", "--repo", str(tmp_path), "--baseline", str(baseline)])
    with pytest.raises(SystemExit) as exit_status:
        cli.main()
    assert exit_status.value.code == 0
    assert "0 new, 1 existing" in capsys.readouterr().out


def test_pr_budget_exhaustion_never_claims_clean(monkeypatch, capsys):
    from sentinel.formatter import print_colored_report
    monkeypatch.setattr(default_config, "quality_max_findings", 1)
    monkeypatch.setattr(default_config, "quality_max_function_lines", 2)
    head = "def f():\n    return 1\n    print('dead')\n"
    result = review_pr(patch("", head), {"core.py": head})
    report = result["consolidated_report"]
    assert report.review_outcome == ReviewOutcome.INCOMPLETE_REVIEW
    assert "**Status**: INCOMPLETE_REVIEW" in report.summary_markdown
    print_colored_report(report, [])
    assert "CLEAN / PASS" not in capsys.readouterr().out


def test_no_python_pr_has_no_quality_rules_to_run():
    result = review_pr(patch("# Old\n", "# New\n", "README.md"), {"README.md": "# New\n"})
    assert result["quality_review"].complete


def test_baseline_ignored_file_is_unassessed_not_resolved(tmp_path, monkeypatch):
    write(tmp_path, "core.py", "def f():\n    return 1\n    print('dead')\n")
    write(tmp_path, "safe.py", "value = 1\n")
    baseline = tmp_path / "baseline.json"
    save_baseline(review_repository(tmp_path)["consolidated_report"], baseline)
    monkeypatch.setattr("sentinel.repository._list_files", lambda root: ["safe.py"])
    review = review_repository(tmp_path, baseline)["quality_review"]
    assert review.complete
    assert not review.baseline.resolved
    assert len(review.baseline.unassessed) == 1


def test_baseline_rejects_source_paths_outside_project(tmp_path):
    write(tmp_path, "safe.py", "value = 1\n")
    report = review_repository(tmp_path)["consolidated_report"]
    baseline = tmp_path / "baseline.json"
    save_baseline(report, baseline)
    payload = json.loads(baseline.read_text())
    payload["findings"] = [{"fingerprint": "fake", "files": ["../outside.py"]}]
    baseline.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="inside the repository"):
        review_repository(tmp_path, baseline)
