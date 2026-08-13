"""Lightweight local tracing with OpenTelemetry-shaped trace/span concepts."""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
import json
import logging
import os
import re
import sqlite3
import time
import traceback
import uuid
from typing import Any, Dict, Iterator, Optional


_trace_id: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)
_span_id: ContextVar[Optional[str]] = ContextVar("span_id", default=None)
logger = logging.getLogger("ai_support_delivery.observability")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_handler)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
logger.propagate = False


def current_trace_id() -> Optional[str]:
    return _trace_id.get()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Optional[Dict[str, Any]]) -> str:
    return json.dumps(value or {}, ensure_ascii=False, default=str)


def _percentile(values: list[float], percentile: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * percentile + 0.999999) - 1))
    return round(ordered[index], 2)


def _stacktrace(exc: BaseException) -> list[dict[str, Any]]:
    """Return code locations without locals or request data."""
    return [
        {"file": frame.filename, "line": frame.lineno, "function": frame.name}
        for frame in traceback.extract_tb(exc.__traceback__)[-20:]
    ]


def _safe_error_message(exc: BaseException) -> Optional[str]:
    if os.getenv("OBSERVABILITY_INCLUDE_ERROR_MESSAGES", "false").lower() != "true":
        return None
    message = str(exc)[:500]
    message = re.sub(r"(?i)(authorization|api[_-]?key|token|secret)(\s*[:=]\s*)[^\s,;]+", r"\1\2[REDACTED]", message)
    message = re.sub(r"(?i)bearer\s+[a-z0-9._~+/-]+=*", "Bearer [REDACTED]", message)
    message = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[REDACTED_EMAIL]", message)
    message = re.sub(r"\bOD\d{9}\b", "[REDACTED_ORDER_ID]", message)
    return message


class SpanHandle:
    def __init__(self, store: "TraceStore", trace_id: str, span_id: str, parent_span_id: Optional[str], name: str, kind: str, attributes: Optional[Dict[str, Any]]) -> None:
        self.store = store
        self.trace_id = trace_id
        self.span_id = span_id
        self.parent_span_id = parent_span_id
        self.name = name
        self.kind = kind
        self.attributes = dict(attributes or {})
        self.started_at = _now()
        self.started_perf = time.perf_counter()
        self.status = "ok"
        self.error_code: Optional[str] = None
        self.error_type: Optional[str] = None
        self.error_message: Optional[str] = None

    def set_attributes(self, **attributes: Any) -> None:
        self.attributes.update({key: value for key, value in attributes.items() if value is not None})

    def set_result(self, success: bool, error_code: Optional[str] = None, **attributes: Any) -> None:
        self.status = "ok" if success else "error"
        self.error_code = error_code
        self.set_attributes(**attributes)

    def set_error(self, exc: BaseException, error_code: Optional[str] = None) -> None:
        self.status = "error"
        self.error_code = error_code
        self.error_type = type(exc).__name__
        self.error_message = _safe_error_message(exc)
        self.attributes["exception.stacktrace"] = _stacktrace(exc)

    def finish(self) -> None:
        ended_at = _now()
        duration_ms = round((time.perf_counter() - self.started_perf) * 1000, 2)
        self.store.finish_span(self, ended_at, duration_ms)


class TraceStore:
    """SQLite trace store for local diagnosis and aggregate analysis."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or os.getenv("OBSERVABILITY_DB_PATH", "runtime/observability.db")
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
        connection = sqlite3.connect(self.db_path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS traces (
                    trace_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    route TEXT NOT NULL,
                    method TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    duration_ms REAL,
                    status TEXT NOT NULL,
                    status_code INTEGER,
                    error_code TEXT,
                    error_type TEXT,
                    error_message TEXT,
                    attributes TEXT NOT NULL
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS spans (
                    span_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    parent_span_id TEXT,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT NOT NULL,
                    duration_ms REAL NOT NULL,
                    status TEXT NOT NULL,
                    error_code TEXT,
                    error_type TEXT,
                    error_message TEXT,
                    attributes TEXT NOT NULL
                )"""
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_spans_trace ON spans(trace_id, started_at)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_spans_name_time ON spans(name, started_at)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_traces_started ON traces(started_at)")
            columns = {row[1] for row in connection.execute("PRAGMA table_info(traces)")}
            if "error_code" not in columns:
                connection.execute("ALTER TABLE traces ADD COLUMN error_code TEXT")

    def begin_trace(self, trace_id: str, *, name: str, route: str, method: str, attributes: Optional[Dict[str, Any]] = None) -> tuple[Any, float]:
        token = _trace_id.set(trace_id)
        _span_id.set(None)
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO traces (trace_id, name, route, method, started_at, status, attributes) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (trace_id, name, route, method, _now(), "running", _json(attributes)),
            )
        return token, time.perf_counter()

    def end_trace(self, trace_id: str, started_perf: float, *, status_code: int, route: Optional[str] = None, error: Optional[BaseException] = None, error_code: Optional[str] = None) -> None:
        status = "error" if error is not None or status_code >= 400 else "ok"
        error_type = type(error).__name__ if error else None
        error_message = _safe_error_message(error) if error else None
        with self._connect() as connection:
            attributes_row = connection.execute("SELECT attributes FROM traces WHERE trace_id = ?", (trace_id,)).fetchone()
            attributes = json.loads(attributes_row["attributes"] or "{}") if attributes_row else {}
            if error is not None:
                attributes["exception.stacktrace"] = _stacktrace(error)
            normalized_name = f"{attributes.get('http.request.method', '')} {route}".strip() if route else None
            connection.execute(
                "UPDATE traces SET name = COALESCE(?, name), route = COALESCE(?, route), ended_at = ?, duration_ms = ?, status = ?, status_code = ?, error_code = ?, error_type = ?, error_message = ?, attributes = ? WHERE trace_id = ?",
                (normalized_name, route, _now(), round((time.perf_counter() - started_perf) * 1000, 2), status, status_code, error_code, error_type, error_message, _json(attributes), trace_id),
            )
        log = logger.error if status == "error" else logger.info
        log(_json({"event": "trace_finished", "trace_id": trace_id, "status": status, "status_code": status_code, "error_code": error_code, "error_type": error_type}))

    def reset_trace(self, token: Any) -> None:
        _span_id.set(None)
        _trace_id.reset(token)

    @contextmanager
    def span(self, name: str, *, kind: str = "internal", attributes: Optional[Dict[str, Any]] = None) -> Iterator[SpanHandle]:
        trace_id = current_trace_id()
        if not trace_id:
            # Direct unit-level service calls remain valid without a request.
            yield _NoopSpan()
            return
        handle = SpanHandle(self, trace_id, uuid.uuid4().hex[:16], _span_id.get(), name, kind, attributes)
        token = _span_id.set(handle.span_id)
        try:
            yield handle
        except BaseException as exc:
            handle.set_error(exc)
            raise
        finally:
            handle.finish()
            _span_id.reset(token)

    def finish_span(self, span: SpanHandle, ended_at: str, duration_ms: float) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO spans
                   (span_id, trace_id, parent_span_id, name, kind, started_at, ended_at, duration_ms, status, error_code, error_type, error_message, attributes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (span.span_id, span.trace_id, span.parent_span_id, span.name, span.kind, span.started_at, ended_at, duration_ms, span.status, span.error_code, span.error_type, span.error_message, _json(span.attributes)),
            )
        log = logger.error if span.status == "error" else logger.info
        log(_json({"event": "span_finished", "trace_id": span.trace_id, "span_id": span.span_id, "parent_span_id": span.parent_span_id, "operation": span.name, "kind": span.kind, "status": span.status, "duration_ms": duration_ms, "error_code": span.error_code, "error_type": span.error_type, **span.attributes}))

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["attributes"] = json.loads(item.get("attributes") or "{}")
        return item

    def get_trace(self, trace_id: str) -> Optional[dict[str, Any]]:
        with self._connect() as connection:
            trace = connection.execute("SELECT * FROM traces WHERE trace_id = ?", (trace_id,)).fetchone()
            spans = connection.execute("SELECT * FROM spans WHERE trace_id = ? ORDER BY started_at, rowid", (trace_id,)).fetchall()
        if trace is None:
            return None
        return {"trace": self._decode(trace), "spans": [self._decode(row) for row in spans]}

    def summary(self, window_minutes: int = 60) -> dict[str, Any]:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=window_minutes)).isoformat()
        with self._connect() as connection:
            traces = connection.execute("SELECT * FROM traces WHERE started_at >= ? AND ended_at IS NOT NULL AND route NOT LIKE '/admin/%' AND route != '/health'", (cutoff,)).fetchall()
            spans = connection.execute(
                """SELECT spans.* FROM spans
                   JOIN traces ON traces.trace_id = spans.trace_id
                   WHERE spans.started_at >= ?
                     AND traces.route NOT LIKE '/admin/%'
                     AND traces.route != '/health'""",
                (cutoff,),
            ).fetchall()
        trace_items = [dict(row) for row in traces]
        span_items = [dict(row) for row in spans]
        durations = [float(item["duration_ms"]) for item in trace_items]
        by_operation: dict[str, list[dict[str, Any]]] = {}
        errors_by_code: dict[str, int] = {}
        for item in span_items:
            by_operation.setdefault(item["name"], []).append(item)
            if item.get("error_code"):
                errors_by_code[item["error_code"]] = errors_by_code.get(item["error_code"], 0) + 1
        for item in trace_items:
            if item.get("error_code"):
                errors_by_code[item["error_code"]] = errors_by_code.get(item["error_code"], 0) + 1
        operations = []
        for name, items in sorted(by_operation.items()):
            values = [float(item["duration_ms"]) for item in items]
            errors = sum(item["status"] == "error" for item in items)
            operations.append({
                "operation": name,
                "count": len(items),
                "error_count": errors,
                "error_rate": round(errors / len(items), 4),
                "latency_ms": {"avg": round(sum(values) / len(values), 2), "p50": _percentile(values, 0.50), "p95": _percentile(values, 0.95), "max": round(max(values), 2)},
            })
        failed_requests = sum(item["status"] == "error" for item in trace_items)
        slowest = sorted(trace_items, key=lambda item: float(item["duration_ms"]), reverse=True)[:10]
        recent_failures = sorted((item for item in trace_items if item["status"] == "error"), key=lambda item: item["started_at"], reverse=True)[:10]
        recent_failed_spans = sorted((item for item in span_items if item["status"] == "error"), key=lambda item: item["started_at"], reverse=True)[:10]
        return {
            "window_minutes": window_minutes,
            "request_count": len(trace_items),
            "request_error_count": failed_requests,
            "request_error_rate": round(failed_requests / len(trace_items), 4) if trace_items else 0,
            "request_latency_ms": {"avg": round(sum(durations) / len(durations), 2) if durations else None, "p50": _percentile(durations, 0.50), "p95": _percentile(durations, 0.95), "max": round(max(durations), 2) if durations else None},
            "errors_by_code": errors_by_code,
            "operations": operations,
            "slowest_traces": [{"trace_id": item["trace_id"], "route": item["route"], "duration_ms": item["duration_ms"], "status": item["status"]} for item in slowest],
            "recent_failed_traces": [{"trace_id": item["trace_id"], "route": item["route"], "duration_ms": item["duration_ms"], "error_code": item["error_code"], "error_type": item["error_type"]} for item in recent_failures],
            "recent_failed_spans": [{"trace_id": item["trace_id"], "span_id": item["span_id"], "operation": item["name"], "duration_ms": item["duration_ms"], "error_code": item["error_code"], "error_type": item["error_type"]} for item in recent_failed_spans],
        }


class _NoopSpan:
    def set_attributes(self, **attributes: Any) -> None:
        pass

    def set_result(self, success: bool, error_code: Optional[str] = None, **attributes: Any) -> None:
        pass

    def set_error(self, exc: BaseException, error_code: Optional[str] = None) -> None:
        pass
