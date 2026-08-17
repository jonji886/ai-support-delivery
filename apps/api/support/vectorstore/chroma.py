"""ChromaVectorStore — Chroma 向量数据库 Provider。

生产/真实运行 provider。
Chroma 不存在时不影响单元测试（通过 factory 延迟导入）"""

from typing import Any, Optional

from .base import VectorSearchResult


class ChromaVectorStore:
    """Chroma 向量数据库 provider。"""

    name = "chroma"

    def __init__(
        self,
        *,
        persist_path: str = "runtime/chroma",
        host: Optional[str] = None,
        port: int = 8000,
    ) -> None:
        try:
            import chromadb
        except ImportError as exc:
            raise ImportError(
                "chromadb is not installed. Install with: pip install chromadb"
            ) from exc

        self._persist_path = persist_path
        self._host = host
        self._port = port
        if host:
            self._client = chromadb.HttpClient(host=host, port=port)
        else:
            self._client = chromadb.PersistentClient(path=persist_path)

    def _get_or_create_collection(self, name: str):
        return self._client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )

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
        col = self._get_or_create_collection(collection)
        col_ids = ids or [f"{collection}-{i}" for i in range(len(documents))]
        metadatas = [{k: str(v) for k, v in doc.items() if v is not None} for doc in documents]
        col.upsert(
            ids=col_ids,
            embeddings=[list(v) for v in vectors],
            metadatas=metadatas,
            documents=[doc.get("text", "") for doc in documents],
        )
        return len(documents)

    def retrieve(
        self,
        *,
        collection: str,
        query_vector: list[float],
        top_k: int = 10,
        filter: Optional[dict[str, Any]] = None,
    ) -> list[VectorSearchResult]:
        try:
            col = self._client.get_collection(collection)
        except Exception:
            return []

        where = None
        if filter:
            where = {k: str(v) for k, v in filter.items()}

        results = col.query(
            query_embeddings=[list(query_vector)],
            n_results=top_k,
            where=where,
        )

        if not results or not results.get("ids") or not results["ids"][0]:
            return []

        ids = results["ids"][0]
        distances = results.get("distances", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        documents = results.get("documents", [[]])[0]

        result_list: list[VectorSearchResult] = []
        for i, _id in enumerate(ids):
            # Chroma 返回 distance（越小越相似），转换为 score（越大越相似）
            distance = distances[i] if i < len(distances) else 1.0
            score = 1.0 - distance  # cosine distance to similarity
            doc = dict(metadatas[i]) if i < len(metadatas) else {}
            if documents and i < len(documents) and documents[i]:
                doc["text"] = documents[i]
            result_list.append(VectorSearchResult(
                id=_id,
                score=score,
                document=doc,
            ))
        return result_list

    def count(self, *, collection: str) -> int:
        try:
            col = self._client.get_collection(collection)
            return col.count()
        except Exception:
            return 0

    def clear(self, *, collection: str) -> int:
        try:
            col = self._client.get_collection(collection)
            count = col.count()
            self._client.delete_collection(collection)
            return count
        except Exception:
            return 0

    def collections(self) -> list[str]:
        return [c.name for c in self._client.list_collections()]
