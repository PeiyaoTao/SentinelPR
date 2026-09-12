"""
Test SentinelPR with local Ollama using gpt-oss:20b.
"""

from sentinel.config import default_config
from sentinel.graph import review_pr

# Configure for local Ollama
default_config.provider = "ollama"
default_config.base_url = "http://localhost:11434/v1"
default_config.fast_model = "gpt-oss:20b"
default_config.frontier_model = "gpt-oss:20b"

# Sample pull request diff & file content
diff_text = """diff --git a/services/payment_service.py b/services/payment_service.py
index 1000001..1000002 100644
--- a/services/payment_service.py
+++ b/services/payment_service.py
@@ -4,4 +4,6 @@ class PaymentProcessor:
 
     def process_transaction(self, user_id: str, items=[]):
+        # Mutates default argument across calls
+        items.append("tx_fee")
         return {"user": user_id, "processed": items}
"""

head_files = {
    "services/payment_service.py": """class PaymentProcessor:
    def __init__(self):
        self.status = "ready"

    def process_transaction(self, user_id: str, items=[]):
        # Mutates default argument across calls
        items.append("tx_fee")
        return {"user": user_id, "processed": items}
"""
}

print("Starting SentinelPR review with Ollama (gpt-oss:20b)...")
result = review_pr(diff=diff_text, head_files=head_files)
report = result.get("consolidated_report")
verified_findings = result.get("verified_findings", [])

if report:
    from sentinel.formatter import print_colored_report
    print_colored_report(report, verified_findings)
