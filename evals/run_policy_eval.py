import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from apps.api.services.policy_search import PolicySearchService


service = PolicySearchService.from_default_data()
queries = json.loads((root / "evals/policy_cases.json").read_text(encoding="utf-8"))
report = service.evaluate(queries)
report["knowledge_update_version"] = "return-policy-v1"
report["knowledge_update_assertion"] = service.rank("退货规则", "US", top_k=1)[0]["document"]["version"] == "return-policy-v1"
(root / "evals/policy-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
