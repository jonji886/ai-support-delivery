"""Small in-memory event store for the demo; production should use durable storage."""

from datetime import datetime, timezone
from typing import Any, Dict, List


class EventStore:
    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []

    def append(self, **event: Any) -> None:
        event.setdefault("occurred_at", datetime.now(timezone.utc).isoformat())
        self.events.append(event)

    def recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        return self.events[-limit:]

    def metrics(self) -> Dict[str, Any]:
        total = len(self.events)
        tool_events = [item for item in self.events if item.get("event_type") == "tool"]
        failures = sum(1 for item in tool_events if not item.get("success"))
        handoffs = sum(1 for item in self.events if item.get("handoff"))
        return {
            "event_count": total,
            "tool_calls": len(tool_events),
            "tool_error_rate": round(failures / len(tool_events), 4) if tool_events else 0,
            "handoff_count": handoffs,
            "conversation_count": sum(1 for item in self.events if item.get("event_type") == "conversation"),
        }
