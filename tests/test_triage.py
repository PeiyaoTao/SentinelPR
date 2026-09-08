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
