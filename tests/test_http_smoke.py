import json
import threading
import time
import urllib.request

import uvicorn


def test_http_server_smoke() -> None:
    config = uvicorn.Config("apps.api.main:app", host="127.0.0.1", port=8766, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(30):
            try:
                with urllib.request.urlopen("http://127.0.0.1:8766/health", timeout=1) as response:
                    assert json.loads(response.read()) == {"status": "ok"}
                break
            except Exception:
                time.sleep(0.1)
        else:
            raise AssertionError("uvicorn HTTP server did not start")
    finally:
        server.should_exit = True
        thread.join(timeout=3)
