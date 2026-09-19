"""
Tests for Triage Agent: Diff hunk parsing, noise filtering, AST slicing, and trust zone tagging.
"""

from sentinel.agents.triage import (
    classify_trust_zone,
    extract_changed_line_numbers,
    is_ignored_file,
    parse_diff_hunks,
    slice_ast_symbols,
)
from sentinel.state import TrustZone


def test_parse_diff_hunks(sample_python_diff):
    hunks = parse_diff_hunks(sample_python_diff)
    assert len(hunks) == 1
    assert hunks[0].file_path == "services/user_service.py"
    assert hunks[0].new_start == 3
    assert hunks[0].new_lines == 4


def test_is_ignored_file():
    patterns = ["package-lock.json", "*.min.js", "*.lock"]

    assert is_ignored_file("package-lock.json", patterns) is True
    assert is_ignored_file("frontend/dist/bundle.min.js", patterns) is True
    assert is_ignored_file("poetry.lock", patterns) is True
    assert is_ignored_file("services/payment.py", patterns) is False


def test_extract_changed_lines(sample_python_diff):
    hunks = parse_diff_hunks(sample_python_diff)
    changed_lines = extract_changed_line_numbers(hunks)

    assert "services/user_service.py" in changed_lines
    # Line 4 is where "+    tags.append("active")" is added
    assert 4 in changed_lines["services/user_service.py"]


def test_slice_ast_symbols():
    code = """import os
import sys

def helper():
    pass

def target_func(x: int):
    y = x + 1
    return y
"""
    # Simulate change at line 8 ("y = x + 1")
    changed_lines = {8}
    symbols = slice_ast_symbols("services/calc.py", code, changed_lines)

    assert len(symbols) == 1
    assert symbols[0].symbol_name == "target_func"
    assert symbols[0].start_line == 7
    assert symbols[0].end_line == 9
    assert len(symbols[0].imports) >= 2


def test_classify_trust_zone():
    assert classify_trust_zone("api/v1/users.py", "def get(): pass") == TrustZone.PERIMETER
    assert classify_trust_zone("controllers/order.py", "def post(): pass") == TrustZone.PERIMETER
    assert classify_trust_zone("domain/order.py", "@app.route('/order')") == TrustZone.PERIMETER
    assert classify_trust_zone("domain/order.py", "def calculate_tax(): pass") == TrustZone.INTERNAL_CORE
    assert classify_trust_zone("clients/stripe_client.py", "def charge(): pass") == TrustZone.INTER_MODULE


def test_slice_ast_symbols_preserves_decorators_and_perimeter_classification():
    code = """from flask import Flask
app = Flask(__name__)

@app.route("/auth/login")
def login_handler():
    return {"status": "ok"}
"""
    # Changed line inside function body (line 6)
    symbols = slice_ast_symbols("domain/auth.py", code, {6})
    assert len(symbols) == 1
    sym = symbols[0]
    assert sym.symbol_name == "login_handler"
    # Decorator starts at line 4
    assert sym.start_line == 4
    assert sym.end_line == 6
    assert "@app.route" in sym.code_snippet
    # Classified as PERIMETER even though file path is domain/auth.py
    assert sym.trust_zone == TrustZone.PERIMETER


def test_deletion_only_hunk_produces_analyzed_symbol():
    from sentinel.agents.triage import parse_diff_hunks
    code = """def process_items(items):
    for x in items:
        process(x)
    return True
"""
    # Simulated deletion diff: deleted a 'break' statement at line 3
    deletion_diff = """--- a/worker.py
+++ b/worker.py
@@ -3,2 +3,1 @@
-        break
         process(x)
"""
    hunks = parse_diff_hunks(deletion_diff)
    changed_lines = extract_changed_line_numbers(hunks)
    assert 3 in changed_lines["worker.py"]

    symbols = slice_ast_symbols("worker.py", code, changed_lines["worker.py"])
    assert len(symbols) == 1
    assert symbols[0].symbol_name == "process_items"


def test_mixed_module_and_function_edits_captures_both():
    code = """API_KEY = "sk-secret-12345"

def do_work():
    return 42
"""
    # Change at line 1 (API_KEY) and line 4 (return 42)
    symbols = slice_ast_symbols("app.py", code, {1, 4})
    symbol_names = [s.symbol_name for s in symbols]
    assert "do_work" in symbol_names
    assert "module_scope" in symbol_names



def test_module_context_keeps_secret_location():
    from sentinel.agents.security import analyze_symbol_security
    source = "# header\n# context\nvalue = 1\napi_key = 'aDifferentCredential123456'\ntail = 2\n"
    scope, = slice_ast_symbols("app.py", source, {4})
    assert scope.code_snippet == "\n".join(source.splitlines()[scope.start_line - 1:scope.end_line])
    finding, = analyze_symbol_security(scope)
    assert finding.start_line == 4


def test_syntax_fallback_keeps_secret_location():
    from sentinel.agents.security import analyze_symbol_security
    source = "not valid python!\n# context\napi_key = 'aDifferentCredential123456'\n"
    scope, = slice_ast_symbols("app.py", source, {3})
    assert (scope.start_line, scope.end_line) == (1, 3)
    finding, = analyze_symbol_security(scope)
    assert finding.start_line == 3
