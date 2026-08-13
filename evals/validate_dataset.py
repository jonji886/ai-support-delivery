import json
from pathlib import Path

required = {"case_id", "category", "input", "preconditions", "expected_intent", "allowed_tools", "expected_fact", "expected_citation", "expected_handoff", "expected_status", "expected_message_contains", "expected_ticket_category", "expected_rule_version", "turns", "version"}
path = Path(__file__).with_name("mvp-50.jsonl")
rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
assert len(rows) >= 50
assert all(required.issubset(row) for row in rows)
assert {row["expected_intent"] for row in rows} == {"logistics", "return", "policy", "complaint", "payment_sensitive", "unknown", "return_application"}
assert {row["category"] for row in rows} == {"normal", "boundary", "tool_error", "risk", "knowledge"}
minimums = {"normal": 20, "boundary": 10, "tool_error": 8, "risk": 8, "knowledge": 4}
for category, minimum in minimums.items():
    assert sum(row["category"] == category for row in rows) >= minimum
assert all(row["allowed_tools"] for row in rows)
print(f"validated {len(rows)} evaluation cases")
