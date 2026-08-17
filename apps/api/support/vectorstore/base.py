"""VectorStoreProvider Protocol — 向量存储抽象。"""

from dataclasses import dataclass
from typing import Any, Optional, Protocol, Sequence


@dataclass
class VectorSearchResult:
    """向量检索结果。"""

    id: str
    score: float
    document: dict[str, Any]
    vector: Optional[list[float]] = None


class VectorStoreProvider(Protocol):
    """向量存储 Provider 协议。"""

    name: str

    def ingest(
        self,
        *,
        collection: str,
        documents: list[dict[str, Any]],
        vectors: list[list[float]],
        ids: Optional[list[str]] = None,
    ) -> int:
        """写入文档向量和元数据。

        Args:
            collection: 集合名称（如 "policy_chunks"）
            documents: 文档元数据列表
            vectors: 对应的向量列表
            ids: 可选 ID 列表

        Returns:
            写入的文档数量
        """
        ...

    def retrieve(
        self,
        *,
        collection: str,
        query_vector: list[float],
        top_k: int = 10,
        filter: Optional[dict[str, Any]] = None,
    ) -> list[VectorSearchResult]:
        """向量检索。

        Args:
            collection: 集合名称
            query_vector: 查询向量
            top_k: 返回数量
            filter: 可选元数据过滤

        Returns:
            检索结果列表
        """
        ...

    def count(self, *, collection: str) -> int:
        """返回集合中的文档数量。"""
        ...

    def clear(self, *, collection: str) -> int:
        """清空集合，返回删除数量。"""
        ...

    def collections(self) -> list[str]:
        """列出所有集合。"""
        ...
