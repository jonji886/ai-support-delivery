"""SQLite-backed event store used by the quality dashboard and audit views."""

from datetime import datetime, timezone
from collections import Counter
import json
import os
import sqlite3
from typing import Any, Dict, List


class EventStore:
    def __init__(self, db_path: str = ":memory:") -> None:
        self.db_path = db_path
        if self.db_path != ":memory:":
            os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
            self._keeper = None
        else:
            self._keeper = sqlite3.connect(":memory:", check_same_thread=False)
            self._keeper.row_factory = sqlite3.Row
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        if self._keeper is not None:
            return self._keeper
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, occurred_at TEXT NOT NULL, payload TEXT NOT NULL)")

    def _all(self) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT payload FROM events ORDER BY id").fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def append(self, **event: Any) -> None:
        event.setdefault("occurred_at", datetime.now(timezone.utc).isoformat())
        with self._connect() as connection:
            connection.execute("INSERT INTO events (occurred_at, payload) VALUES (?, ?)", (event["occurred_at"], json.dumps(event, ensure_ascii=False)))

    def recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT payload FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [json.loads(row["payload"]) for row in reversed(rows)]

    def events_for_trace(self, trace_id: str) -> List[Dict[str, Any]]:
        return [event for event in self._all() if event.get("trace_id") == trace_id]

    def metrics(self) -> Dict[str, Any]:
        events = self._all()
        conversations = [item for item in events if item.get("event_type") == "conversation"]
        tool_events = [item for item in events if item.get("event_type") == "tool"]
        failures = sum(1 for item in tool_events if not item.get("success"))
        handoffs = sum(1 for item in conversations if item.get("handoff"))
        policy_conversations = [item for item in conversations if item.get("intent") == "policy"]
        cited_policy = sum(1 for item in policy_conversations if item.get("citations"))
        risk_intents = {"payment_sensitive", "complaint", "unknown"}
        risks = [item for item in conversations if item.get("intent") in risk_intents or item.get("handoff")]
        intents = Counter(item.get("intent") or "unknown" for item in conversations)
        errors = Counter(item.get("error_code") for item in events if item.get("error_code"))
        now = datetime.now(timezone.utc)
        buckets = []
        for offset in range(11, -1, -1):
            bucket_time = now.replace(minute=0, second=0, microsecond=0)
            bucket_time = bucket_time.replace(hour=(bucket_time.hour - offset) % 24)
            label = bucket_time.strftime("%H:00")
            bucket_events = []
            for item in conversations:
                try:
                    occurred = datetime.fromisoformat(str(item.get("occurred_at", "")).replace("Z", "+00:00"))
                except ValueError:
                    continue
                if occurred.strftime("%H:00") == label:
                    bucket_events.append(item)
            bucket_tools = [item for item in tool_events if str(item.get("occurred_at", "")).startswith(bucket_time.strftime("%Y-%m-%dT%H:"))]
            bucket_failures = sum(1 for item in bucket_tools if not item.get("success"))
            buckets.append({"label": label, "conversations": len(bucket_events), "handoffs": sum(1 for item in bucket_events if item.get("handoff")), "tool_success_rate": round((1 - bucket_failures / len(bucket_tools)) * 100, 1) if bucket_tools else None})
        tool_success_rate = round((1 - failures / len(tool_events)) * 100, 1) if tool_events else None
        handoff_rate = round(handoffs / len(conversations) * 100, 1) if conversations else None
        citation_rate = round(cited_policy / len(policy_conversations) * 100, 1) if policy_conversations else None
        status = "正常"
        if (tool_success_rate is not None and tool_success_rate < 95) or (handoff_rate is not None and handoff_rate > 30) or risks:
            status = "需关注"
        return {
            "event_count": len(events),
            "tool_calls": len(tool_events),
            "tool_error_rate": round(failures / len(tool_events), 4) if tool_events else 0,
            "tool_success_rate": tool_success_rate,
            "handoff_count": handoffs,
            "handoff_rate": handoff_rate,
            "conversation_count": len(conversations),
            "citation_rate": citation_rate,
            "risk_count": len(risks),
            "status": status,
            "intent_distribution": dict(intents),
            "error_distribution": dict(errors),
            "trend": buckets,
        }
