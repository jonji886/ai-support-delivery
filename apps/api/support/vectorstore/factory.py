"""VectorStore factory — 根据配置创建 provider。"""

import os
from typing import Optional

from .base import VectorStoreProvider
from .local import LocalVectorStore


def create_vector_store(provider: Optional[str] = None, **kwargs) -> VectorStoreProvider:
    """根据配置创建 VectorStoreProvider。

    Args:
        provider: provider 名称（local | chroma），默认从 VECTOR_STORE_PROVIDER 环境变量读取
        **kwargs: provider 特定参数

    Returns:
        VectorStoreProvider 实例
    """
    provider_name = provider or os.getenv("VECTOR_STORE_PROVIDER", "local")

    if provider_name == "local":
        return LocalVectorStore()

    if provider_name == "chroma":
        from .chroma import ChromaVectorStore
        return ChromaVectorStore(
            persist_path=kwargs.get("persist_path", os.getenv("CHROMA_PERSIST_PATH", "runtime/chroma")),
            host=kwargs.get("host") or os.getenv("CHROMA_HOST"),
            port=int(kwargs.get("port", os.getenv("CHROMA_PORT", "8000"))),
        )

    raise ValueError(f"unsupported vector store provider: {provider_name}")
