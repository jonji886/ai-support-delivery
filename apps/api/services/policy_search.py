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
import hashlib
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
                # Python's built-in hash is randomized between processes. A
                # stable digest keeps local evaluation reproducible.
                index = int.from_bytes(hashlib.sha256(gram.encode("utf-8")).digest()[:8], "big") % len(vector)
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
        min_evidence_score: float = 0.65,
        default_strategy: str = "fusion",
    ) -> None:
        self._validate_documents(documents)
        self.documents = self._chunk_documents(documents)
        self.embedding_provider = embedding_provider or DeterministicEmbeddingProvider()
        self.reranker_provider = reranker_provider or LexicalRerankerProvider()
        self.production_mode = production_mode
        self.min_vector_score = min_vector_score
        self.min_evidence_score = min_evidence_score
        self.default_strategy = default_strategy
        if default_strategy not in {"lexical", "vector", "fusion", "fusion_rerank"}:
            raise ValueError(f"unsupported retrieval strategy: {default_strategy}")
        if production_mode and (
            self.embedding_provider.name == "deterministic-test-embedding"
            or self.reranker_provider.name == "lexical-test-reranker"
        ):
            raise RuntimeError("生产模式必须配置真实 embedding 和 Cross-Encoder/model reranker")
        self._document_vectors = self.embedding_provider.embed([item["text"] for item in self.documents])

    @staticmethod
    def _validate_documents(documents: list[dict[str, Any]]) -> None:
        required = {"policy_id", "title", "version", "status", "effective_from", "region", "source", "content", "answerability"}
        for index, document in enumerate(documents):
            missing = sorted(required - document.keys())
            if missing:
                raise ValueError(f"knowledge document {index} missing fields: {', '.join(missing)}")
            if document["status"] not in {"draft", "published", "expired"}:
                raise ValueError(f"knowledge document {document['version']} has invalid status")
            try:
                date.fromisoformat(document["effective_from"])
                if document.get("effective_to"):
                    date.fromisoformat(document["effective_to"])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"knowledge document {document['version']} has invalid lifecycle date") from exc
            if document.get("effective_to") and document["effective_to"] <= document["effective_from"]:
                raise ValueError(f"knowledge document {document['version']} effective_to must be after effective_from")
            answerability = document["answerability"]
            if not answerability.get("domain_terms") or not answerability.get("focus_terms"):
                raise ValueError(f"knowledge document {document['version']} requires answerability terms")

    @classmethod
    def from_default_data(cls, **overrides: Any) -> "PolicySearchService":
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
        min_vector_score = float(os.getenv("POLICY_MIN_VECTOR_SCORE", "0.35"))
        min_evidence_score = float(os.getenv("POLICY_MIN_EVIDENCE_SCORE", os.getenv("POLICY_MIN_SIMILARITY", "0.65")))
        options = {
            "embedding_provider": embedding,
            "reranker_provider": reranker,
            "production_mode": production,
            "min_vector_score": min_vector_score,
            "min_evidence_score": min_evidence_score,
            "default_strategy": os.getenv("RAG_RETRIEVAL_STRATEGY", "fusion_rerank" if production else "fusion"),
        }
        options.update(overrides)
        return cls(documents, **options)

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

    @staticmethod
    def _is_currently_published(document: dict[str, Any], today: str) -> bool:
        """Treat lifecycle metadata as a hard admission rule, never a rank bonus."""
        if document.get("status") != "published":
            return False
        if document.get("effective_from", "9999-12-31") > today:
            return False
        effective_to = document.get("effective_to")
        return not effective_to or today < effective_to

    def _eligible_indices(self, region: str) -> set[int]:
        today = date.today().isoformat()
        region = region.upper()
        return {
            index
            for index, document in enumerate(self.documents)
            if document.get("region") in {"ALL", region} and self._is_currently_published(document, today)
        }

    def _lexical_candidates(self, question: str, eligible: set[int], limit: int) -> list[dict[str, Any]]:
        normalized_question = _normalize(question)
        question_grams = _ngrams(question)
        candidates = []
        for index, document in enumerate(self.documents):
            if index not in eligible:
                continue
            keywords = document.get("keywords", [])
            keyword_hits = sum(1 for keyword in keywords if _normalize(keyword) in normalized_question)
            overlap = len(question_grams & _ngrams(document["text"])) / max(len(question_grams), 1)
            if keyword_hits or overlap >= 0.15:
                candidates.append({"index": index, "lexical_score": keyword_hits + overlap})
        return sorted(candidates, key=lambda item: item["lexical_score"], reverse=True)[:limit]

    def _vector_candidates(self, question: str, eligible: set[int], limit: int) -> list[dict[str, Any]]:
        query_vector = self.embedding_provider.embed([question])[0]
        candidates = []
        for index, document in enumerate(self.documents):
            if index in eligible:
                candidates.append({"index": index, "vector_score": _cosine(query_vector, self._document_vectors[index])})
        return [item for item in sorted(candidates, key=lambda item: item["vector_score"], reverse=True) if item["vector_score"] >= self.min_vector_score][:limit]

    @staticmethod
    def _rrf(rank: int, constant: int = 60) -> float:
        return 1.0 / (constant + rank + 1)

    def rank(self, question: str, region: str, top_k: int = 5, strategy: Optional[str] = None) -> list[dict[str, Any]]:
        strategy = strategy or self.default_strategy
        if strategy not in {"lexical", "vector", "fusion", "fusion_rerank"}:
            raise ValueError(f"unsupported retrieval strategy: {strategy}")
        eligible = self._eligible_indices(region)
        lexical = self._lexical_candidates(question, eligible, max(top_k * 3, 10)) if strategy != "vector" else []
        vector = self._vector_candidates(question, eligible, max(top_k * 3, 10)) if strategy != "lexical" else []
        # A vector-only hit must clear a higher semantic threshold. This
        # prevents unrelated short questions from being mapped to a policy by
        # a noisy test/local embedding; production thresholds are configurable.
        if strategy in {"fusion", "fusion_rerank"} and not lexical:
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
        if strategy == "lexical":
            pool = sorted(merged.values(), key=lambda item: item.get("lexical_score", 0), reverse=True)[: max(top_k * 2, 10)]
        elif strategy == "vector":
            pool = sorted(merged.values(), key=lambda item: item.get("vector_score", 0), reverse=True)[: max(top_k * 2, 10)]
        else:
            pool = sorted(merged.values(), key=lambda item: item["fusion_score"], reverse=True)[: max(top_k * 2, 10)]
        # Aggregate chunks before reranking so one historical chunk cannot win
        # over the current version of the same policy.
        by_version: dict[tuple[str, str], dict[str, Any]] = {}
        for item in pool:
            document = self.documents[item["index"]]
            key = (document["policy_id"], document["version"])
            if key not in by_version or item["fusion_score"] > by_version[key]["fusion_score"]:
                by_version[key] = item
        pool = list(by_version.values())
        rerank_scores = (
            self.reranker_provider.score(question, [self.documents[item["index"]]["content"] for item in pool])
            if strategy == "fusion_rerank"
            else [0.0] * len(pool)
        )
        ranked = []
        for item, rerank_score in zip(pool, rerank_scores):
            document = self.documents[item["index"]]
            item.update({"document": document, "rerank_score": rerank_score, "effective": True, "strategy": strategy})
            if strategy == "lexical":
                item["final_score"] = item.get("lexical_score", 0)
            elif strategy == "vector":
                item["final_score"] = item.get("vector_score", 0)
            elif strategy == "fusion":
                item["final_score"] = item["fusion_score"]
            else:
                item["final_score"] = rerank_score * 0.7 + item["fusion_score"] * 0.3
            ranked.append(item)
        ranked.sort(key=lambda item: item["final_score"], reverse=True)
        return ranked[:top_k]

    @staticmethod
    def _evidence_score(question: str, document: dict[str, Any]) -> float:
        """Deterministic POC answerability gate backed by explicit knowledge metadata.

        Retrieval relevance only says two texts concern a similar topic. The
        knowledge owner must also declare which user intents the document can
        substantiate. Production can replace this transparent gate with a
        calibrated NLI/model verifier while preserving the same contract.
        """
        normalized = _normalize(question)
        answerability = document.get("answerability", {})
        domain_terms = [_normalize(term) for term in answerability.get("domain_terms", [])]
        focus_terms = [_normalize(term) for term in answerability.get("focus_terms", [])]
        excluded_terms = [_normalize(term) for term in answerability.get("excluded_terms", [])]
        if any(term and term in normalized for term in excluded_terms):
            return 0.0
        domain_hit = any(term and term in normalized for term in domain_terms)
        focus_hit = any(term and term in normalized for term in focus_terms)
        if domain_hit and focus_hit:
            return 0.90
        # Permit typo-tolerant evidence only when both dimensions have strong
        # character-bigram overlap. This remains below exact metadata evidence.
        query_grams = _ngrams(question)
        domain_overlap = max((len(query_grams & _ngrams(term)) / max(len(_ngrams(term)), 1) for term in domain_terms), default=0)
        focus_overlap = max((len(query_grams & _ngrams(term)) / max(len(_ngrams(term)), 1) for term in focus_terms), default=0)
        return round(0.75 * min(domain_overlap, focus_overlap), 4)

    def evaluate(self, queries: list[dict[str, Any]], region: str = "US", strategy: Optional[str] = None) -> dict[str, Any]:
        strategy = strategy or self.default_strategy
        recall_hits = 0
        top1_hits = 0
        unsupported_hits = 0
        supported_total = 0
        unsupported_total = 0
        for query in queries:
            ranked = self.rank(query["question"], query.get("region", region), top_k=query.get("top_k", 5), strategy=strategy)
            versions = [item["document"]["version"] for item in ranked]
            expected = query["expected_version"]
            if expected == "none":
                unsupported_total += 1
                result = self.search(query["question"], query.get("region", region), "eval", strategy=strategy)
                unsupported_hits += int(not result.success)
                continue
            supported_total += 1
            recall_hits += int(expected in versions)
            top1_hits += int(bool(versions) and versions[0] == expected)
        total = len(queries)
        return {
            "total_queries": total,
            "supported_queries": supported_total,
            "recall_at_k": round(recall_hits / supported_total, 4) if supported_total else 0,
            "retrieval_top1_accuracy": round(top1_hits / supported_total, 4) if supported_total else 0,
            "unsupported_rejection_rate": round(unsupported_hits / unsupported_total, 4) if unsupported_total else 0,
            "embedding_provider": self.embedding_provider.name,
            "reranker_provider": self.reranker_provider.name,
            "strategy": strategy,
        }

    def search(self, question: str, region: str, trace_id: str, strategy: Optional[str] = None) -> ToolResponse:
        strategy = strategy or self.default_strategy
        ranked = self.rank(question, region, top_k=5, strategy=strategy)
        if not ranked:
            return ToolResponse.failure(trace_id, "404_POLICY_NOT_FOUND", "没有找到可验证的生效规则，建议转人工。", 404)
        document = ranked[0]["document"]
        evidence_score = self._evidence_score(question, document)
        if evidence_score < self.min_evidence_score:
            failure = ToolResponse.failure(trace_id, "404_POLICY_NOT_FOUND", "检索结果与问题主题相关，但证据不足以支持确定性回答，建议转人工。", 404)
            failure.data = {
                "retrieval": {
                    "strategy": strategy,
                    "candidate_count": len(ranked),
                    "evidence_score": evidence_score,
                    "evidence_threshold": self.min_evidence_score,
                    "rejection_reason": "evidence_score_below_threshold",
                }
            }
            return failure
        data = {
            # Chunks are used for retrieval/reranking; the final answer keeps
            # the complete versioned policy so business facts are not lost at
            # chunk boundaries.
            "answer": document["content"],
            "citations": [{
                "policy_id": document["policy_id"],
                "title": document["title"],
                "version": document["version"],
                "status": document["status"],
                "effective_from": document["effective_from"],
                "effective_to": document.get("effective_to"),
                "source": document["source"],
                "chunk_id": document["chunk_id"],
                "quoted_text": document["text"],
            }],
            "retrieval": {
                "strategy": strategy,
                "candidate_count": len(ranked),
                "embedding_provider": self.embedding_provider.name,
                "reranker_provider": self.reranker_provider.name,
                "rerank_score": ranked[0]["rerank_score"],
                "evidence_score": evidence_score,
                "evidence_threshold": self.min_evidence_score,
            },
        }
        logger.info("tool_call", extra={"event": "tool_call", "tool_name": "search_policy", "trace_id": trace_id, "success": True, "error_code": None})
        return ToolResponse.success_result(data, trace_id, "已找到生效规则。")
