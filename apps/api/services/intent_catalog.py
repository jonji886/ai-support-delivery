"""Versioned intent definitions and deterministic safety-first routing."""

import json
import re
from pathlib import Path
from typing import Any, Optional


def _normalize(value: str) -> str:
    normalized = re.sub(r"\s+", "", value.lower())
    return normalized.translate(str.maketrans({"貨": "货", "尋": "寻"})).replace("查寻", "查询").replace("物留", "物流")


class IntentCatalog:
    REQUIRED_INTENTS = {"logistics", "return", "policy", "complaint", "payment_sensitive", "unknown"}
    REQUIRED_FIELDS = {
        "intent_id", "display_name", "description", "owner", "risk_level", "priority",
        "required_slots", "allowed_tools", "forbidden_tools", "risk_labels", "signals",
        "positive_examples", "hard_negative_examples",
    }
    REQUIRED_ROUTE_TOOLS = {
        "logistics": "query_order_logistics",
        "return": "check_return_eligibility",
        "policy": "search_policy",
        "complaint": "create_service_ticket",
        "payment_sensitive": "create_service_ticket",
        "unknown": "handoff_human",
    }

    def __init__(self, payload: dict[str, Any]) -> None:
        self._validate(payload)
        self.version = payload["version"]
        self.owner = payload["owner"]
        self.decision_policy = payload["decision_policy"]
        self.intents = {item["intent_id"]: item for item in payload["intents"]}

    @classmethod
    def from_default_data(cls) -> "IntentCatalog":
        return cls.from_path(Path(__file__).parents[3] / "config" / "intent-catalog.json")

    @classmethod
    def from_path(cls, path: Path) -> "IntentCatalog":
        return cls(json.loads(path.read_text(encoding="utf-8")))

    @classmethod
    def _validate(cls, payload: dict[str, Any]) -> None:
        if not payload.get("version") or not payload.get("owner") or not payload.get("decision_policy"):
            raise ValueError("intent catalog requires version, owner and decision_policy")
        intents = payload.get("intents")
        if not isinstance(intents, list) or not intents:
            raise ValueError("intent catalog intents must be a non-empty list")
        ids = [item.get("intent_id") for item in intents]
        if len(ids) != len(set(ids)) or not cls.REQUIRED_INTENTS.issubset(ids):
            raise ValueError("intent catalog intents must contain unique required intent ids")
        for item in intents:
            missing = cls.REQUIRED_FIELDS - item.keys()
            if missing:
                raise ValueError(f"intent {item.get('intent_id')} missing fields: {sorted(missing)}")
            overlap = set(item["allowed_tools"]) & set(item["forbidden_tools"])
            if overlap:
                raise ValueError(f"intent {item['intent_id']} has conflicting tool permissions: {sorted(overlap)}")
            if not item["description"] or not item["owner"] or not item["positive_examples"] or not item["hard_negative_examples"]:
                raise ValueError(f"intent {item['intent_id']} requires boundaries, examples and owner")
        by_id = {item["intent_id"]: item for item in intents}
        for intent_id, tool_name in cls.REQUIRED_ROUTE_TOOLS.items():
            if tool_name not in by_id[intent_id]["allowed_tools"] or tool_name in by_id[intent_id]["forbidden_tools"]:
                raise ValueError(f"intent {intent_id} must allow its controlled route tool {tool_name}")

    def get(self, intent_id: str) -> dict[str, Any]:
        return self.intents[intent_id]

    def is_known(self, intent_id: str) -> bool:
        return intent_id in self.intents

    def is_tool_allowed(self, intent_id: str, tool_name: str) -> bool:
        definition = self.intents.get(intent_id) or self.intents["unknown"]
        return tool_name in definition["allowed_tools"] and tool_name not in definition["forbidden_tools"]

    def classify(self, message: str, previous_intent: Optional[str] = None) -> dict[str, Any]:
        normalized = _normalize(message)
        matched: list[tuple[int, str, list[str]]] = []
        for intent_id, definition in self.intents.items():
            if intent_id == "unknown":
                continue
            hits = [signal for signal in definition["signals"] if _normalize(signal) in normalized]
            if hits:
                matched.append((int(definition["priority"]), intent_id, hits))

        # Explicit policy language wins over lower-risk return/logistics words,
        # while complaint/payment retain safety priority above every normal task.
        matched.sort(reverse=True)
        follow_up = any(normalized.startswith(prefix) for prefix in ("那", "还", "继续", "然后", "现在", "这个", "它")) or normalized in {"呢", "怎么办", "怎么处理"}
        if not matched and previous_intent in {"logistics", "return", "policy"} and (follow_up or len(normalized) <= 12):
            return {
                "intent": previous_intent,
                "secondary_intents": [],
                "risk_labels": [],
                "confidence": 0.90,
                "margin": 0.20,
                "source": "catalog_context",
                "catalog_version": self.version,
            }
        if not matched:
            unknown = self.intents["unknown"]
            return {
                "intent": "unknown", "secondary_intents": [], "risk_labels": unknown["risk_labels"],
                "confidence": 0.40, "margin": 0.05, "source": "catalog_no_match", "catalog_version": self.version,
            }
        primary = matched[0][1]
        secondary = []
        for _, intent_id, _ in matched[1:]:
            if intent_id != primary and intent_id not in secondary:
                secondary.append(intent_id)
        risk_labels = self.intents[primary]["risk_labels"]
        return {
            "intent": primary,
            "secondary_intents": secondary,
            "risk_labels": risk_labels,
            "confidence": 0.99,
            "margin": 0.50 if len(matched) == 1 else 0.30,
            "source": "catalog_rule",
            "matched_signals": {intent_id: hits for _, intent_id, hits in matched},
            "catalog_version": self.version,
        }
