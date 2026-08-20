"""Run a reproducible end-to-end simulated OMS timeout scenario.

The script starts the synthetic customer systems and the API with isolated
SQLite files, injects a timeout through the customer HTTP boundary, then
prints the safe Tool response and the resulting trace spans.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]
MOCK_PORT = 18001
API_PORT = 18000


def wait_for_health(url: str, process: subprocess.Popen[bytes], timeout_seconds: float = 15) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"service exited before health check: {url}")
        try:
            if httpx.get(url, timeout=0.5).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    raise TimeoutError(f"service did not become healthy: {url}")


def stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ai-support-oms-timeout-") as temp_dir:
        base_env = dict(os.environ)
        base_env.update(
            {
                "DEEPSEEK_ENABLED": "false",
                "APP_ENV": "demo",
                "MOCK_CUSTOMER_SYSTEMS_BASE_URL": f"http://127.0.0.1:{MOCK_PORT}",
                "MOCK_CUSTOMER_FAULT": "timeout",
                "EVENTS_DB_PATH": str(Path(temp_dir) / "events.db"),
                "SUPPORT_DB_PATH": str(Path(temp_dir) / "support.db"),
                "OBSERVABILITY_DB_PATH": str(Path(temp_dir) / "observability.db"),
            }
        )
        processes: list[subprocess.Popen[bytes]] = []
        try:
            mock = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "apps.mock_customer_systems.app:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(MOCK_PORT),
                ],
                cwd=ROOT,
                env=base_env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            processes.append(mock)
            wait_for_health(f"http://127.0.0.1:{MOCK_PORT}/health", mock)

            api = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "apps.api.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(API_PORT),
                ],
                cwd=ROOT,
                env=base_env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            processes.append(api)
            api_base = f"http://127.0.0.1:{API_PORT}"
            wait_for_health(f"{api_base}/health", api)

            response = httpx.post(
                f"{api_base}/assist",
                json={
                    "message": "订单到哪里了？",
                    "order_id": "OD202608001",
                    "session_id": "demo-oms-timeout",
                },
                headers={"X-User-Id": "user-demo-001"},
                timeout=20,
            )
            body = response.json()
            print("User-visible response:")
            print(
                json.dumps(
                    {
                        "http_status": response.status_code,
                        "error_code": body.get("error_code"),
                        "message": body.get("message"),
                        "handoff": body.get("handoff"),
                        "trace_id": body.get("trace_id"),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )

            trace_id = body.get("trace_id")
            if not trace_id:
                raise AssertionError("response did not include trace_id")
            trace_response = httpx.get(
                f"{api_base}/admin/traces/{trace_id}",
                headers={"X-Role": "supervisor"},
                timeout=5,
            )
            trace_response.raise_for_status()
            spans = trace_response.json().get("spans", [])
            print("Trace spans:")
            for span in spans:
                print(
                    f"- {span['name']}: {span['status']} "
                    f"{span.get('error_code') or '-'} {span['duration_ms']}ms"
                )

            if body.get("error_code") != "504_EXTERNAL_TIMEOUT":
                raise AssertionError(f"unexpected error code: {body.get('error_code')}")
            if body.get("handoff") is not True:
                raise AssertionError("timeout response did not request human handoff")
            return 0
        finally:
            for process in reversed(processes):
                stop(process)


if __name__ == "__main__":
    raise SystemExit(main())
