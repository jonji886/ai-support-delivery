"""VectorStoreProvider — 向量存储抽象。

支持：
  - local: 确定性内存 provider（测试默认）
  - chroma: Chroma 向量数据库（真实运行）

原则：
  - 测试默认使用 local provider，不依赖外部服务
  - Chroma 不存在时不导致单元测试失败
  - 保持 RAG Eval 可重复
"""

from .base import VectorStoreProvider, VectorSearchResult
from .local import LocalVectorStore
from .factory import create_vector_store

__all__ = [
    "VectorStoreProvider",
    "VectorSearchResult",
    "LocalVectorStore",
    "create_vector_store",
]
