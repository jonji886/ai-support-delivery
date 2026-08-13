"""Optional DeepSeek adapter. The model never becomes the source of business facts."""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("ai_support_delivery.model")


def _load_local_env() -> None:
    """Load simple KEY=VALUE/export KEY=VALUE entries for local demo startup."""
    env_path = Path(__file__).parents[3] / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        line = line[7:] if line.startswith("export ") else line
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


class DeepSeekClient:
    def __init__(self, api_key: Optional[str] = None, base_url: str = "https://api.deepseek.com", model: str = "deepseek-chat", timeout: float = 3.0) -> None:
        _load_local_env()
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.api_key) and os.getenv("DEEPSEEK_ENABLED", "true").lower() not in {"0", "false", "no"}

    def classify(self, message: str, trace_id: str) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        payload = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": 30,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": '你是售后意图分类器。只输出 JSON：{"intent":"logistics|return|policy|complaint|unknown","confidence":0到1,"margin":0到1}。投诉、退款争议、支付问题归类 complaint。'},
                {"role": "user", "content": message},
            ],
        }
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            intent = json.loads(content).get("intent")
            confidence = float(json.loads(content).get("confidence", 0))
            margin = float(json.loads(content).get("margin", 1))
            if intent in {"logistics", "return", "policy", "complaint", "unknown"}:
                logger.info("model_call", extra={"event": "model_call", "provider": "deepseek", "model": self.model, "trace_id": trace_id, "success": True})
                return {"intent": intent, "confidence": confidence, "margin": margin}
        except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            # Model failure is non-fatal: deterministic routing remains the safe fallback.
            logger.warning("model_call_failed", extra={"event": "model_call", "provider": "deepseek", "model": self.model, "trace_id": trace_id, "success": False, "error_type": type(exc).__name__})
        return None
