"""Versioned, hand-labelled fixtures, including known gaps and clean counterexamples.

Labels describe desired review behavior, not assertions that current rules pass.
No fixture is imported or executed by the behavior benchmark.
"""
VERSION = "behavior-v1"


def expected(title, path="core.py", lane="defect_leads", line=1):
    return {"title": title, "path": path, "line": line, "lane": lane}


CASES = [
    {"id": "mutable_state_leak", "files": {"core.py": "def collect(items=[]):\n    items.append(1)\n    return items\n"},
     "expected": [expected("Dangerous Mutable Default Argument")], "rationale": "Calls without an argument share and mutate the same list."},
    {"id": "read_only_default", "files": {"core.py": "def count(items=[]):\n    return len(items)\n"},
     "expected": [], "rationale": "The function neither mutates nor exposes the default; replacing it is optional style, not a demonstrated state leak."},
    {"id": "fresh_default", "files": {"core.py": "def collect(items=None):\n    if items is None: items = []\n    items.append(1)\n    return items\n"},
     "expected": [], "rationale": "Each omitted argument creates fresh state."},
    {"id": "sql_interpolation", "files": {"core.py": "def lookup(cursor, user_input):\n    cursor.execute(f'SELECT * FROM users WHERE id = {user_input}')\n    return cursor.fetchone()\n"},
     "expected": [expected("SQL Injection via String Formatting", line=2)], "rationale": "The fixture contract treats user_input as raw external input; interpolation permits SQL syntax injection."},
    {"id": "parameterized_sql", "files": {"core.py": "def lookup(cursor, user_input):\n    cursor.execute('SELECT * FROM users WHERE id = %s', (user_input,))\n    return cursor.fetchone()\n"},
     "expected": [], "rationale": "The DB adapter contract uses a bound parameter, not SQL interpolation."},
    {"id": "synthetic_secret_fixture", "files": {"tests/test_scan.py": "def test_scan(tmp_path):\n    (tmp_path / 'core.py').write_text(\"api_key = 'abcdefghijklmnop1234'\\n\")\n"},
     "expected": [], "rationale": "Known fabricated scanner input embedded in a test is not a credential exposure."},
    {"id": "test_credential_assignment", "files": {"tests/test_client.py": "api_key = 'exampleCredentialValue12345'\n"},
     "expected": [expected("Hardcoded Credential/Secret", path="tests/test_client.py")],
     "rationale": "Detect an actual credential-shaped assignment even in a test. This fabricated benchmark value is not a live secret; the label tests pattern-detection coverage."},
    {"id": "locked_global_update", "files": {"core.py": "import threading\nlock = threading.Lock()\ntotal = 0\ndef increment():\n    global total\n    with lock:\n        total += 1\n"},
     "expected": [], "rationale": "All accesses in the supplied fixture use one lock; a global update alone is not an actionable concurrency defect."},
    {"id": "required_perimeter_check", "files": {"api/handler.py": "def handle(raw: dict):\n    if raw is None:\n        raise ValueError('request required')\n    return raw['id']\n"},
     "expected": [], "rationale": "The public input boundary must validate raw requests."},
    {"id": "off_by_one_known_gap", "files": {"core.py": "def last(items):\n    return items[len(items)]\n"},
     "expected": [expected("Out-of-bounds last-element access", line=2)], "rationale": "For nonempty sequences, the last index is len(items)-1. The label deliberately includes a currently unsupported defect."},
    {"id": "correct_last_element", "files": {"core.py": "def last(items):\n    return items[-1]\n"},
     "expected": [], "rationale": "The fixture contract requires a nonempty sequence."},
    {"id": "unreachable_observation", "files": {"core.py": "def value():\n    return 1\n    unused = 2\n"},
     "expected": [expected("Unreachable statements after unconditional control transfer", lane="advisory_observations", line=3)],
     "rationale": "Record the static unreachable-code observation separately from defect-lead precision."},
]
