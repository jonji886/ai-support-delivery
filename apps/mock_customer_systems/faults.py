"""Fault injection helpers for the mock customer systems.

Fault injection is deterministic and driven by request metadata (header or
query parameter) so that integration tests and demos can reproduce failures
without touching configuration.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse

#: Supported fault modes.
FAULT_MODES = {"normal", "429", "500", "timeout", "slow_response", "invalid_schema"}

_SLOW_MS_HEADER = "X-Mock-Slow-Ms"
_FAULT_HEADER = "X-Fault-Inject"
_FAULT_QUERY = "fault"


def fault_mode(request: Request) -> str:
    """Read the requested fault mode from header or query parameter."""
    mode = request.headers.get(_FAULT_HEADER) or request.query_params.get(_FAULT_QUERY)
    if mode not in FAULT_MODES:
        return "normal"
    return mode


def slow_ms(request: Request) -> int:
    raw = request.headers.get(_SLOW_MS_HEADER) or request.query_params.get("slow_ms") or "3000"
    try:
        return max(0, min(int(raw), 30000))
    except ValueError:
        return 3000


async def apply_fault(request: Request) -> Optional[JSONResponse]:
    """Apply the requested fault; return a response to short-circuit, or None.

    * ``429``          -> 429 Too Many Requests (retryable upstream error)
    * ``500``          -> 500 Internal Server Error (unrecoverable upstream error)
    * ``timeout``      -> sleep 60s, effectively exceeding any caller timeout
    * ``slow_response``-> sleep ``X-Mock-Slow-Ms`` ms then continue normally
    * ``invalid_schema``-> caller receives a malformed JSON body
    """
    mode = fault_mode(request)
    if mode == "429":
        return JSONResponse(
            status_code=429,
            content={
                "code": "RATE_LIMITED",
                "message": "Mock system is rate-limiting this request.",
                "retry_after": 1,
            },
        )
    if mode == "500":
        return JSONResponse(
            status_code=500,
            content={"code": "INTERNAL_ERROR", "message": "Mock system internal error."},
        )
    if mode == "timeout":
        await asyncio.sleep(60)
        return JSONResponse(status_code=504, content={"code": "TIMEOUT", "message": "Mock system timed out."})
    if mode == "slow_response":
        await asyncio.sleep(slow_ms(request) / 1000.0)
        return None
    return None


def malformed_payload(*, error_hint: str = "") -> JSONResponse:
    """Return a 200 with a malformed body to exercise schema validation."""
    return JSONResponse(
        status_code=200,
        content={
            "unexpected_field": "this payload deliberately misses the contract",
            "hint": error_hint or "invalid_schema fault injected",
        },
    )


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
