import os
import socket
import tempfile
import threading
import time

# Tests must remain deterministic and must never call the user's external model API.
os.environ["DEEPSEEK_ENABLED"] = "false"
os.environ["SUPPORT_DB_PATH"] = tempfile.mktemp(prefix="ai-support-test-", suffix=".db")
os.environ["CONVERSATION_DB_PATH"] = tempfile.mktemp(prefix="ai-support-conversation-test-", suffix=".db")
os.environ["EVENTS_DB_PATH"] = tempfile.mktemp(prefix="ai-support-events-test-", suffix=".db")
os.environ["OBSERVABILITY_DB_PATH"] = tempfile.mktemp(prefix="ai-support-observability-test-", suffix=".db")
os.environ["LOG_LEVEL"] = "CRITICAL"

# ---------------------------------------------------------------------------
# Real HTTP integration boundary: boot the Mock Customer Systems service.
#
# Agent-side services reach the customer systems over HTTP (see apps/api/main.py),
# so tests run a real uvicorn server on a random port and point the API at it via
# MOCK_CUSTOMER_SYSTEMS_BASE_URL. This module-level setup runs before test
# modules import `apps.api.main`, guaranteeing the HTTP mode is exercised.
# ---------------------------------------------------------------------------
import httpx  # noqa: E402
import uvicorn  # noqa: E402

from apps.mock_customer_systems.app import app as _mock_customer_app  # noqa: E402


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


_MOCK_PORT = _find_free_port()
_MOCK_BASE_URL = f"http://127.0.0.1:{_MOCK_PORT}"
os.environ["MOCK_CUSTOMER_SYSTEMS_BASE_URL"] = _MOCK_BASE_URL

_mock_server = uvicorn.Server(
    uvicorn.Config(_mock_customer_app, host="127.0.0.1", port=_MOCK_PORT, log_level="warning")
)
threading.Thread(target=_mock_server.run, daemon=True).start()

_ready = False
for _ in range(200):
    try:
        if httpx.get(f"{_MOCK_BASE_URL}/health", timeout=0.5).status_code == 200:
            _ready = True
            break
    except Exception:
        time.sleep(0.05)
if not _ready:
    raise RuntimeError(f"Mock customer systems failed to start on {_MOCK_BASE_URL}")
