"""
Pytest configuration and fixtures for SentinelPR tests.
"""

import sys
from pathlib import Path
import pytest

# Ensure src directory is on sys.path
src_path = str(Path(__file__).parent.parent / "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)


@pytest.fixture
def sample_python_diff():
    return """diff --git a/services/user_service.py b/services/user_service.py
index 1234567..89abcdef 100644
--- a/services/user_service.py
+++ b/services/user_service.py
@@ -3,3 +3,4 @@
 def register_user(username: str, tags=[]):
+    tags.append("active")
     return {"username": username, "tags": tags}
"""


@pytest.fixture
def sample_head_files():
    return {
        "services/user_service.py": """# User management service

def register_user(username: str, tags=[]):
    tags.append("active")
    return {"username": username, "tags": tags}
"""
    }
