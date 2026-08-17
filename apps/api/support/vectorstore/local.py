"""LocalVectorStore — 确定性内存向量存储。

测试默认 provider。不依赖外部服务。
使用余弦相似度进行线性扫描。
"""

import math
from typing import Any, Optional, Sequence

from .base import VectorSearchResult


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


class LocalVectorStore:
    """内存确定性向量存储。"""

    name = "local"

    def __init__(self) -> None:
        self._collections: dict[str, list[dict[str, Any]]] = {}

    def ingest(
        self,
        *,
        collection: str,
        documents: list[dict[str, Any]],
        vectors: list[list[float]],
        ids: Optional[list[str]] = None,
    ) -> int:
        if len(documents) != len(vectors):
            raise ValueError(f"documents ({len(documents)}) and vectors ({len(vectors)}) length mismatch")
        if collection not in self._collections:
            self._collections[collection] = []
        for i, (doc, vec) in enumerate(zip(documents, vectors)):
            entry_id = ids[i] if ids else f"{collection}-{len(self._collections[collection])}"
            self._collections[collection].append({
                "id": entry_id,
                "document": doc,
                "vector": list(vec),
            })
        return len(documents)

    def retrieve(
        self,
        *,
        collection: str,
        query_vector: list[float],
        top_k: int = 10,
        filter: Optional[dict[str, Any]] = None,
    ) -> list[VectorSearchResult]:
        entries = self._collections.get(collection, [])
        scored: list[tuple[float, dict[str, Any]]] = []
        for entry in entries:
            # 应用过滤
            if filter:
                doc = entry["document"]
                if not all(str(doc.get(k)) == str(v) for k, v in filter.items()):
                    continue
            score = _cosine(query_vector, entry["vector"])
            scored.append((score, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            VectorSearchResult(
                id=entry["id"],
                score=score,
                document=entry["document"],
                vector=entry["vector"],
            )
            for score, entry in scored[:top_k]
        ]

    def count(self, *, collection: str) -> int:
        return len(self._collections.get(collection, []))

    def clear(self, *, collection: str) -> int:
        count = len(self._collections.get(collection, []))
        self._collections.pop(collection, None)
        return count

    def collections(self) -> list[str]:
        return list(self._collections.keys())
