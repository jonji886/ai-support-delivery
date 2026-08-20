"""Boot the Mock Customer Systems HTTP service for eval scripts.

apps/api/main.py 现在通过 HTTP Client 访问客户系统（MOCK_CUSTOMER_SYSTEMS_BASE_URL），
eval 脚本必须像 tests/conftest.py 一样，在 import apps.api.main 之前先启动 mock 服务
并设置 MOCK_CUSTOMER_SYSTEMS_BASE_URL，否则所有需要 OMS / Logistics 的 case 都会
因连接失败进入熔断（503_CIRCUIT_OPEN / 503_EXTERNAL_UNAVAILABLE）。
"""
from __future__ import annotations

import os
import socket
import threading
import time
from typing import Optional


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def boot_mock_customer_systems(base_url: Optional[str] = None) -> str:
    """Start the mock customer systems service and export its base URL.

    If ``base_url`` is provided (already running service), only export it.
    Otherwise boot a real uvicorn server on a random free port.
    """
    if base_url:
        os.environ["MOCK_CUSTOMER_SYSTEMS_BASE_URL"] = base_url
        return base_url

    import httpx  # noqa: E402
    import uvicorn  # noqa: E402
    from apps.mock_customer_systems.app import app as _mock_customer_app  # noqa: E402

    port = _find_free_port()
    base = f"http://127.0.0.1:{port}"
    os.environ["MOCK_CUSTOMER_SYSTEMS_BASE_URL"] = base

    server = uvicorn.Server(
        uvicorn.Config(_mock_customer_app, host="127.0.0.1", port=port, log_level="warning")
    )
    threading.Thread(target=server.run, daemon=True).start()

    ready = False
    for _ in range(200):
        try:
            if httpx.get(f"{base}/health", timeout=0.5).status_code == 200:
                ready = True
                break
        except Exception:
            time.sleep(0.05)
    if not ready:
        raise RuntimeError(f"Mock customer systems failed to start on {base}")
    return base
