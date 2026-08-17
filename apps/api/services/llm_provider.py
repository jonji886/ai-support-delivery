"""LLMProvider — LLM 模型 Provider 抽象。

支持：
  - DeepSeekProvider: 现有 DeepSeek 集成
  - MockProvider: 测试用

重点展示：
  - timeout
  - retry
  - error mapping
  - fallback
  - observability

真实业务事实不能由 LLM Provider 生成。
"""

from typing import Any, Optional, Protocol


class LLMProvider(Protocol):
    """LLM Provider 协议。"""

    name: str

    @property
    def enabled(self) -> bool: ...

    @property
    def model(self) -> str: ...

    def classify(self, message: str, trace_id: str) -> Optional[dict[str, Any]]:
        """意图分类。"""
        ...

    def generate(self, prompt: str, trace_id: str, *, max_tokens: int = 500) -> Optional[str]:
        """生成文本。"""
        ...


class MockLLMProvider:
    """Mock LLM Provider — 测试用。

    不调用真实 API，返回确定性结果。
    """

    name = "mock-llm"
    model = "mock-model"

    def __init__(self, *, enabled: bool = False) -> None:
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    def classify(self, message: str, trace_id: str) -> Optional[dict[str, Any]]:
        if not self._enabled:
            return None
        # 返回一个简单的 mock 意图
        return {
            "intent": "logistics",
            "confidence": 0.80,
            "source": "mock_provider",
            "secondary_intents": [],
        }

    def generate(self, prompt: str, trace_id: str, *, max_tokens: int = 500) -> Optional[str]:
        if not self._enabled:
            return None
        return f"[Mock LLM Response] Prompt length: {len(prompt)}"


def create_llm_provider(
    *,
    provider: Optional[str] = None,
    timeout: float = 5.0,
    max_retries: int = 2,
) -> LLMProvider:
    """根据配置创建 LLM Provider。

    Args:
        provider: provider 名称（deepseek | mock），默认从 LLM_PROVIDER 环境变量读取
        timeout: 请求超时秒数
        max_retries: 最大重试次数

    Returns:
        LLMProvider 实例
    """
    import os

    provider_name = provider or os.getenv("LLM_PROVIDER", "deepseek")

    if provider_name == "mock":
        return MockLLMProvider(enabled=os.getenv("DEEPSEEK_ENABLED", "false").lower() == "false")

    if provider_name == "deepseek":
        from apps.api.services.deepseek import DeepSeekClient
        return DeepSeekClient(timeout=timeout, max_retries=max_retries)

    raise ValueError(f"unsupported LLM provider: {provider_name}")
