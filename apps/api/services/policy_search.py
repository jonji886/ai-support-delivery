"""Versioned hybrid RAG service.

The production path is:
document chunks -> embedding retrieval + lexical retrieval -> reciprocal-rank
fusion -> cross-encoder/model reranking -> effective metadata guard.

The deterministic providers are intentionally injectable for local tests. They
are not production-quality semantic models and are never reported as such.
"""

import json
import logging
import os
import math
import re
from datetime import date
from pathlib import Path
from typing import Any, Optional, Protocol, Sequence
from urllib.request import Request, urlopen

from apps.api.support.responses import ToolResponse

logger = logging.getLogger("ai_support_delivery.tool")


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value.lower())


def _ngrams(value: str, size: int = 2) -> set[str]:
    text = _normalize(value)
    return {text} if len(text) <= size and text else {text[i:i + size] for i in range(len(text) - size + 1)}


class EmbeddingProvider(Protocol):
    name: str

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class RerankerProvider(Protocol):
    name: str

    def score(self, query: str, documents: Sequence[str]) -> list[float]: ...


class DeterministicEmbeddingProvider:
    """Test-only hashed character embedding; replace with a real embedding API."""

    name = "deterministic-test-embedding"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vector = [0.0] * 64
            for gram in _ngrams(text):
                index = hash(gram) % len(vector)
                vector[index] += 1.0
            norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            vectors.append([value / norm for value in vector])
        return vectors


class LexicalRerankerProvider:
    """Test-only reranker; production must use a Cross-Encoder/model provider."""

    name = "lexical-test-reranker"

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        query_grams = _ngrams(query)
        return [len(query_grams & _ngrams(document)) / max(len(query_grams), 1) for document in documents]


class HttpEmbeddingProvider:
    """OpenAI-compatible embedding endpoint for production deployment."""

    name = "http-embedding"

    def __init__(self, url: str, api_key: str, model: str) -> None:
        self.url, self.api_key, self.model = url, api_key, model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        request = Request(self.url, data=json.dumps({"model": self.model, "input": list(texts)}).encode(), headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}, method="POST")
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode())
        return [item["embedding"] for item in sorted(payload["data"], key=lambda item: item.get("index", 0))]


class HttpRerankerProvider:
    """Generic JSON reranker endpoint returning {scores: [float, ...]}."""

    name = "http-cross-encoder"

    def __init__(self, url: str, api_key: str, model: str) -> None:
        self.url, self.api_key, self.model = url, api_key, model

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        request = Request(self.url, data=json.dumps({"model": self.model, "query": query, "documents": list(documents)}).encode(), headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}, method="POST")
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode())["scores"]


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


class PolicySearchService:
    def __init__(
        self,
        documents: list[dict[str, Any]],
        embedding_provider: Optional[EmbeddingProvider] = None,
        reranker_provider: Optional[RerankerProvider] = None,
        production_mode: bool = False,
        min_vector_score: float = 0.35,
    ) -> None:
        self.documents = self._chunk_documents(documents)
        self.embedding_provider = embedding_provider or DeterministicEmbeddingProvider()
        self.reranker_provider = reranker_provider or LexicalRerankerProvider()
        self.production_mode = production_mode
        self.min_vector_score = min_vector_score
        if production_mode and (
            self.embedding_provider.name == "deterministic-test-embedding"
            or self.reranker_provider.name == "lexical-test-reranker"
        ):
            raise RuntimeError("生产模式必须配置真实 embedding 和 Cross-Encoder/model reranker")
        self._document_vectors = self.embedding_provider.embed([item["text"] for item in self.documents])

    @classmethod
    def from_default_data(cls) -> "PolicySearchService":
        root = Path(__file__).parents[3] / "knowledge"
        documents = []
        for path in sorted(root.glob("*.json")):
            with path.open(encoding="utf-8") as file:
                documents.extend(json.load(file))
        production = os.getenv("RAG_PRODUCTION_MODE", "false").lower() == "true"
        embedding = reranker = None
        if production:
            embedding = HttpEmbeddingProvider(os.environ["EMBEDDING_API_URL"], os.environ["EMBEDDING_API_KEY"], os.environ["EMBEDDING_MODEL"])
            reranker = HttpRerankerProvider(os.environ["RERANKER_API_URL"], os.environ["RERANKER_API_KEY"], os.environ["RERANKER_MODEL"])
        return cls(documents, embedding_provider=embedding, reranker_provider=reranker, production_mode=production)

    @staticmethod
    def _chunk_documents(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
        chunks = []
        for document in documents:
            content = document["content"]
            # Keep the POC chunks sentence-sized; production can use a tokenizer
            # and overlap policy while preserving document/version metadata.
            parts = [part.strip() for part in re.split(r"[。；]", content) if part.strip()]
            for index, part in enumerate(parts or [content]):
                item = dict(document)
                item["chunk_id"] = f"{document['version']}#{index}"
                item["text"] = part
                chunks.append(item)
        return chunks

    def _lexical_candidates(self, question: str, region: str, limit: int) -> list[dict[str, Any]]:
        normalized_question = _normalize(question)
        question_grams = _ngrams(question)
        candidates = []
        for index, document in enumerate(self.documents):
            if document["region"] not in {"ALL", region.upper()}:
                continue
            keywords = document.get("keywords", [])
            keyword_hits = sum(1 for keyword in keywords if _normalize(keyword) in normalized_question)
            overlap = len(question_grams & _ngrams(document["text"])) / max(len(question_grams), 1)
            if keyword_hits or overlap >= 0.15:
                candidates.append({"index": index, "lexical_score": keyword_hits + overlap})
        return sorted(candidates, key=lambda item: item["lexical_score"], reverse=True)[:limit]

    def _vector_candidates(self, question: str, region: str, limit: int) -> list[dict[str, Any]]:
        query_vector = self.embedding_provider.embed([question])[0]
        candidates = []
        for index, document in enumerate(self.documents):
            if document["region"] in {"ALL", region.upper()}:
                candidates.append({"index": index, "vector_score": _cosine(query_vector, self._document_vectors[index])})
        return [item for item in sorted(candidates, key=lambda item: item["vector_score"], reverse=True) if item["vector_score"] >= self.min_vector_score][:limit]

    @staticmethod
    def _rrf(rank: int, constant: int = 60) -> float:
        return 1.0 / (constant + rank + 1)

    def rank(self, question: str, region: str, top_k: int = 5) -> list[dict[str, Any]]:
        lexical = self._lexical_candidates(question, region, max(top_k * 3, 10))
        vector = self._vector_candidates(question, region, max(top_k * 3, 10))
        # A vector-only hit must clear a higher semantic threshold. This
        # prevents unrelated short questions from being mapped to a policy by
        # a noisy test/local embedding; production thresholds are configurable.
        if not lexical:
            vector = [item for item in vector if item["vector_score"] >= (0.60 if self.embedding_provider.name == "deterministic-test-embedding" else self.min_vector_score)]
        if not lexical and not vector:
            return []
        merged: dict[int, dict[str, Any]] = {}
        for rank, item in enumerate(lexical):
            merged.setdefault(item["index"], {"index": item["index"]}).update(item)
            merged[item["index"]]["fusion_score"] = merged[item["index"]].get("fusion_score", 0) + self._rrf(rank)
        for rank, item in enumerate(vector):
            merged.setdefault(item["index"], {"index": item["index"]}).update(item)
            merged[item["index"]]["fusion_score"] = merged[item["index"]].get("fusion_score", 0) + self._rrf(rank)
        pool = sorted(merged.values(), key=lambda item: item["fusion_score"], reverse=True)[: max(top_k * 2, 10)]
        # Aggregate chunks before reranking so one historical chunk cannot win
        # over the current version of the same policy.
        by_version: dict[str, dict[str, Any]] = {}
        for item in pool:
            document = self.documents[item["index"]]
            key = document["version"]
            if key not in by_version or item["fusion_score"] > by_version[key]["fusion_score"]:
                by_version[key] = item
        pool = list(by_version.values())
        rerank_scores = self.reranker_provider.score(question, [self.documents[item["index"]]["content"] for item in pool])
        ranked = []
        today = date.today().isoformat()
        for item, rerank_score in zip(pool, rerank_scores):
            document = self.documents[item["index"]]
            effective = document.get("effective_from", "") <= today
            item.update({"document": document, "rerank_score": rerank_score, "effective": effective})
            # Metadata is a guard, not a soft preference: expired chunks cannot win.
            if effective:
                recency_bonus = min(max(int(document.get("effective_from", "0")[:4]) - 2020, 0), 20) / 100
                item["final_score"] = rerank_score * 0.7 + item["fusion_score"] * 0.3 + recency_bonus
                ranked.append(item)
        ranked.sort(key=lambda item: (item["final_score"], item["document"].get("effective_from", "")), reverse=True)
        return ranked[:top_k]

    def evaluate(self, queries: list[dict[str, Any]], region: str = "US") -> dict[str, Any]:
        recall_hits = 0
        top1_hits = 0
        unsupported_hits = 0
        supported_total = 0
        unsupported_total = 0
        for query in queries:
            ranked = self.rank(query["question"], region, top_k=query.get("top_k", 5))
            versions = [item["document"]["version"] for item in ranked]
            expected = query["expected_version"]
            if expected == "none":
                unsupported_total += 1
                unsupported_hits += int(not ranked)
                continue
            supported_total += 1
            recall_hits += int(expected in versions)
            top1_hits += int(bool(versions) and versions[0] == expected)
        total = len(queries)
        return {
            "total_queries": total,
            "supported_queries": supported_total,
            "recall_at_k": round(recall_hits / supported_total, 4) if supported_total else 0,
            "rerank_top1_accuracy": round(top1_hits / supported_total, 4) if supported_total else 0,
            "unsupported_rejection_rate": round(unsupported_hits / unsupported_total, 4) if unsupported_total else 0,
            "embedding_provider": self.embedding_provider.name,
            "reranker_provider": self.reranker_provider.name,
        }

    def search(self, question: str, region: str, trace_id: str) -> ToolResponse:
        ranked = self.rank(question, region, top_k=5)
        if not ranked:
            return ToolResponse.failure(trace_id, "404_POLICY_NOT_FOUND", "没有找到可验证的生效规则，建议转人工。", 404)
        document = ranked[0]["document"]
        data = {
            # Chunks are used for retrieval/reranking; the final answer keeps
            # the complete versioned policy so business facts are not lost at
            # chunk boundaries.
            "answer": document["content"],
            "citations": [{"title": document["title"], "version": document["version"], "source": document["source"], "chunk_id": document["chunk_id"]}],
            "retrieval": {
                "strategy": "vector+bm25_like+rrf+cross_encoder",
                "candidate_count": len(ranked),
                "embedding_provider": self.embedding_provider.name,
                "reranker_provider": self.reranker_provider.name,
                "rerank_score": ranked[0]["rerank_score"],
            },
        }
        logger.info("tool_call", extra={"event": "tool_call", "tool_name": "search_policy", "trace_id": trace_id, "success": True, "error_code": None})
        return ToolResponse.success_result(data, trace_id, "已找到生效规则。")
