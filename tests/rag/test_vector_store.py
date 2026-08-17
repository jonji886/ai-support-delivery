"""VectorStoreProvider 测试。"""

import pytest

from apps.api.support.vectorstore import LocalVectorStore, create_vector_store
from apps.api.support.vectorstore.base import VectorSearchResult


class TestLocalVectorStore:
    """LocalVectorStore 确定性内存向量存储测试。"""

    @pytest.fixture
    def store(self):
        return LocalVectorStore()

    @pytest.fixture
    def sample_docs(self):
        return [
            {"text": "退货政策", "policy_id": "P001", "version": "v1"},
            {"text": "物流时效", "policy_id": "P002", "version": "v1"},
            {"text": "退款流程", "policy_id": "P003", "version": "v1"},
        ]

    @pytest.fixture
    def sample_vectors(self):
        return [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ]

    def test_ingest_and_count(self, store, sample_docs, sample_vectors):
        n = store.ingest(
            collection="policies",
            documents=sample_docs,
            vectors=sample_vectors,
        )
        assert n == 3
        assert store.count(collection="policies") == 3

    def test_retrieve_by_vector(self, store, sample_docs, sample_vectors):
        store.ingest(
            collection="policies",
            documents=sample_docs,
            vectors=sample_vectors,
        )
        # 查询向量接近第一个文档
        results = store.retrieve(
            collection="policies",
            query_vector=[1.0, 0.0, 0.0],
            top_k=2,
        )
        assert len(results) == 2
        assert results[0].document["policy_id"] == "P001"
        assert results[0].score > results[1].score

    def test_retrieve_with_filter(self, store, sample_docs, sample_vectors):
        store.ingest(
            collection="policies",
            documents=sample_docs,
            vectors=sample_vectors,
        )
        results = store.retrieve(
            collection="policies",
            query_vector=[1.0, 0.0, 0.0],
            top_k=10,
            filter={"version": "v1"},
        )
        assert all(r.document["version"] == "v1" for r in results)

    def test_retrieve_empty_collection(self, store):
        results = store.retrieve(
            collection="nonexistent",
            query_vector=[1.0, 0.0, 0.0],
        )
        assert len(results) == 0

    def test_clear(self, store, sample_docs, sample_vectors):
        store.ingest(
            collection="policies",
            documents=sample_docs,
            vectors=sample_vectors,
        )
        deleted = store.clear(collection="policies")
        assert deleted == 3
        assert store.count(collection="policies") == 0

    def test_collections(self, store, sample_docs, sample_vectors):
        store.ingest(collection="col1", documents=sample_docs, vectors=sample_vectors)
        store.ingest(collection="col2", documents=sample_docs[:1], vectors=sample_vectors[:1])
        cols = store.collections()
        assert "col1" in cols
        assert "col2" in cols

    def test_ingest_length_mismatch(self, store):
        with pytest.raises(ValueError, match="length mismatch"):
            store.ingest(
                collection="test",
                documents=[{"a": 1}],
                vectors=[[1.0], [2.0]],
            )


class TestFactory:
    """VectorStore factory 测试。"""

    def test_create_local_default(self):
        store = create_vector_store()
        assert store.name == "local"

    def test_create_local_explicit(self):
        store = create_vector_store("local")
        assert store.name == "local"

    def test_create_local_env(self, monkeypatch):
        monkeypatch.setenv("VECTOR_STORE_PROVIDER", "local")
        store = create_vector_store()
        assert store.name == "local"

    def test_create_chroma_not_installed(self, monkeypatch):
        """Chroma 未安装时应抛出 ImportError。"""
        monkeypatch.setenv("VECTOR_STORE_PROVIDER", "chroma")
        # 如果 chromadb 未安装，应该抛出 ImportError
        try:
            import chromadb  # noqa: F401
            pytest.skip("chromadb is installed")
        except ImportError:
            with pytest.raises(ImportError, match="chromadb is not installed"):
                create_vector_store()

    def test_unsupported_provider(self):
        with pytest.raises(ValueError, match="unsupported vector store provider"):
            create_vector_store("redis")
