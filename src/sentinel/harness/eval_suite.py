"""
Synthetic PR benchmark generator and ground-truth evaluation suite for SentinelPR.
"""

from typing import Any, Dict, List
import textwrap

from sentinel.graph import review_pr
from sentinel.state import FindingCategory, Severity


SYNTHETIC_PRS: List[Dict[str, Any]] = [
    {
        "id": "CASE-01-MUTABLE-DEFAULT",
        "title": "PR introducing mutable default list in helper",
        "diff": textwrap.dedent("""
            diff --git a/services/cart.py b/services/cart.py
            index 1111111..2222222 100644
            --- a/services/cart.py
            +++ b/services/cart.py
            @@ -6,3 +6,4 @@
             def add_item(cart_id: str, items=[]):
            +    items.append("new_item")
                 return items
        """).strip(),
        "head_files": {
            "services/cart.py": textwrap.dedent("""
                # Shopping cart service

                def get_cart(cart_id: str):
                    return {"id": cart_id}

                def add_item(cart_id: str, items=[]):
                    items.append("new_item")
                    return items
            """).strip()
        },
        "expected_categories": [FindingCategory.LOGIC],
        "expected_findings_count": 1,
    },
    {
        "id": "CASE-02-GHOST-NULL-CHECK",
        "title": "PR introducing overprotective ghost null check in internal domain core",
        "diff": textwrap.dedent("""
            diff --git a/domain/pricing.py b/domain/pricing.py
            index 3333333..4444444 100644
            --- a/domain/pricing.py
            +++ b/domain/pricing.py
            @@ -4,3 +4,5 @@
             def compute_discount(order: Order) -> float:
            +    if order is None:
            +        return 0.0
                 return order.total * 0.1
        """).strip(),
        "head_files": {
            "domain/pricing.py": textwrap.dedent("""
                class Order:
                    total: float

                def compute_discount(order: Order) -> float:
                    if order is None:
                        return 0.0
                    return order.total * 0.1
            """).strip()
        },
        "expected_categories": [FindingCategory.ANTI_BLOAT],
        "expected_findings_count": 1,
    },
    {
        "id": "CASE-03-PERIMETER-INPUT-VALIDATION",
        "title": "PR adding necessary defensive validation at public API route (MUST NOT BE FLAGGED AS BLOAT)",
        "diff": textwrap.dedent("""
            diff --git a/api/checkout.py b/api/checkout.py
            index 5555555..6666666 100644
            --- a/api/checkout.py
            +++ b/api/checkout.py
            @@ -4,4 +4,6 @@
             @app.route("/checkout", methods=["POST"])
             def handle_checkout(request):
            +    if request is None or not request.json:
            +        return {"error": "Invalid request"}, 400
                 return {"status": "ok"}
            diff --git a/tests/test_checkout.py b/tests/test_checkout.py
            new file mode 100644
            --- /dev/null
            +++ b/tests/test_checkout.py
            @@ -0,0 +1,2 @@
            +def test_checkout_validation():
            +    pass
        """).strip(),
        "head_files": {
            "api/checkout.py": textwrap.dedent("""
                from flask import Flask, request
                app = Flask(__name__)

                @app.route("/checkout", methods=["POST"])
                def handle_checkout(request):
                    if request is None or not request.json:
                        return {"error": "Invalid request"}, 400
                    return {"status": "ok"}
            """).strip(),
            "tests/test_checkout.py": "def test_checkout_validation(): pass\n",
        },
        "expected_categories": [],
        "expected_findings_count": 0,  # Protected by Trust Boundary and has tests!
    },
    {
        "id": "CASE-04-SQL-INJECTION",
        "title": "PR introducing SQL injection vulnerability via string concatenation",
        "diff": textwrap.dedent("""
            diff --git a/api/users.py b/api/users.py
            index 7777777..8888888 100644
            --- a/api/users.py
            +++ b/api/users.py
            @@ -1,3 +1,3 @@
             def get_user(cursor, user_id):
            +    cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")
                 return cursor.fetchone()
            diff --git a/tests/test_users.py b/tests/test_users.py
            new file mode 100644
            --- /dev/null
            +++ b/tests/test_users.py
            @@ -0,0 +1,2 @@
            +def test_get_user():
            +    pass
        """).strip(),
        "head_files": {
            "api/users.py": textwrap.dedent("""
                def get_user(cursor, user_id):
                    cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")
                    return cursor.fetchone()
            """).strip(),
            "tests/test_users.py": "def test_get_user(): pass\n",
        },
        "expected_categories": [FindingCategory.SECURITY],
        "expected_findings_count": 1,
    },
    {
        "id": "CASE-05-CLEAN-REFACTOR",
        "title": "PR with clean code changes and no defects",
        "diff": textwrap.dedent("""
            diff --git a/utils/math_ops.py b/utils/math_ops.py
            index 9999999..0000000 100644
            --- a/utils/math_ops.py
            +++ b/utils/math_ops.py
            @@ -1,3 +1,4 @@
             def add(a: int, b: int) -> int:
            +    # Simple addition
                 return a + b
        """).strip(),
        "head_files": {
            "utils/math_ops.py": textwrap.dedent("""
                def add(a: int, b: int) -> int:
                    # Simple addition
                    return a + b
            """).strip()
        },
        "expected_categories": [],
        "expected_findings_count": 0,
    },
    {
        "id": "CASE-06-UNTESTED-PERIMETER-RISK",
        "title": "PR modifying public API route without accompanying tests (High Blast Radius)",
        "diff": textwrap.dedent("""
            diff --git a/api/v1/auth.py b/api/v1/auth.py
            index 1212121..3434343 100644
            --- a/api/v1/auth.py
            +++ b/api/v1/auth.py
            @@ -1,3 +1,4 @@
             def login(credentials):
            +    # Modify login route with no tests
                 return {"token": "session_token"}
        """).strip(),
        "head_files": {
            "api/v1/auth.py": textwrap.dedent("""
                def login(credentials):
                    # Modify login route with no tests
                    return {"token": "session_token"}
            """).strip()
        },
        "expected_categories": [FindingCategory.RISK],
        "expected_findings_count": 1,
    },
]


def run_eval_suite() -> Dict[str, Any]:
    """
    Executes all synthetic benchmark PRs and outputs precision and recall metrics.
    """
    results = []
    passed_tests = 0

    print("==================================================")
    print("[START] Starting SentinelPR Synthetic Benchmark Suite")
    print("==================================================")

    for case in SYNTHETIC_PRS:
        case_id = case["id"]
        title = case["title"]
        print(f"\nEvaluating {case_id}: {title}...")

        state = review_pr(
            diff=case["diff"],
            head_files=case["head_files"],
        )
        verified_findings = state.get("verified_findings", [])
        actual_count = len(verified_findings)
        expected_count = case["expected_findings_count"]

        # Check if categories match expected
        actual_categories = [f.category for f in verified_findings]
        expected_categories = case["expected_categories"]

        passed = (actual_count == expected_count) and all(
            cat in actual_categories for cat in expected_categories
        )

        if passed:
            passed_tests += 1
            status_str = "[PASS]"
        else:
            status_str = f"[FAIL] (Expected {expected_count} findings, got {actual_count})"

        print(f"  Result: {status_str}")
        for f in verified_findings:
            print(f"    - [{f.category.value} / {f.severity.value}] {f.title} ({f.file_path}:L{f.start_line})")

        results.append({
            "case_id": case_id,
            "passed": passed,
            "actual_count": actual_count,
            "expected_count": expected_count,
            "findings": verified_findings,
        })

    total_tests = len(SYNTHETIC_PRS)
    accuracy = (passed_tests / total_tests) * 100.0

    print("\n==================================================")
    print(f"[SUMMARY] Evaluation Complete: {passed_tests}/{total_tests} passed ({accuracy:.1f}%)")
    print("==================================================")

    return {
        "total": total_tests,
        "passed": passed_tests,
        "accuracy": accuracy,
        "cases": results,
    }


if __name__ == "__main__":
    run_eval_suite()
