from apps.api.services.policy_search import PolicySearchService
import pytest


def test_hybrid_search_recovers_chinese_typo_and_reranks_current_rule() -> None:
    service = PolicySearchService.from_default_data()
    ranked = service.rank("海处仓发货后几天到货", "US")
    assert ranked
    assert ranked[0]["document"]["version"] == "shipping-policy-v1"


def test_knowledge_update_prefers_new_effective_version() -> None:
    service = PolicySearchService.from_default_data()
    ranked = service.rank("退货规则", "US")
    assert ranked[0]["document"]["version"] == "return-policy-v1"
    assert ranked[0]["document"]["effective_from"] > "2025-01-01"


def test_expired_version_is_not_a_retrieval_candidate_even_when_query_quotes_it() -> None:
    service = PolicySearchService.from_default_data()

    ranked = service.rank("美国退货 7 天旧规则", "US")

    assert ranked
    assert all(item["document"]["version"] != "return-policy-v0" for item in ranked)


def test_same_domain_question_without_support_is_rejected() -> None:
    service = PolicySearchService.from_default_data()

    for question in ("退货需要发票吗", "商品保修多久", "物流保险赔不赔", "海外仓配送可以预约时间吗", "退货需要支付手续费吗"):
        result = service.search(question, "US", f"trace-{question}")
        assert result.success is False
        assert result.error_code == "404_POLICY_NOT_FOUND"


def test_evidence_threshold_is_an_answer_gate_not_only_a_vector_filter() -> None:
    service = PolicySearchService.from_default_data(min_evidence_score=0.99)

    result = service.search("海外仓发货后几天到货", "US", "trace-threshold")

    assert result.success is False
    assert result.data["retrieval"]["rejection_reason"] == "evidence_score_below_threshold"


def test_citation_contains_the_exact_supporting_chunk_and_lifecycle_metadata() -> None:
    service = PolicySearchService.from_default_data()

    result = service.search("海外仓发货后几天到货", "US", "trace-citation")

    assert result.success is True
    citation = result.data["citations"][0]
    assert citation["quoted_text"]
    assert citation["quoted_text"] in result.data["answer"]
    assert citation["status"] == "published"
    assert citation["effective_from"]


def test_each_retrieval_strategy_is_available_for_ablation() -> None:
    service = PolicySearchService.from_default_data()

    for strategy in ("lexical", "vector", "fusion", "fusion_rerank"):
        ranked = service.rank("海外仓物流时效", "US", strategy=strategy)
        assert ranked
        assert ranked[0]["strategy"] == strategy


def test_invalid_knowledge_lifecycle_fails_fast() -> None:
    invalid = [{
        "policy_id": "return-policy-us-standard",
        "title": "坏规则",
        "version": "bad-v1",
        "status": "published",
        "effective_from": "2026-08-01",
        "effective_to": "2026-01-01",
        "region": "US",
        "source": "knowledge/bad.json",
        "content": "坏规则",
        "keywords": ["坏规则"],
        "answerability": {"domain_terms": ["退货"], "focus_terms": ["期限"]},
    }]

    with pytest.raises(ValueError, match="effective_to"):
        PolicySearchService(invalid)


def test_evidence_threshold_can_be_configured_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POLICY_MIN_EVIDENCE_SCORE", "0.88")

    service = PolicySearchService.from_default_data()

    assert service.min_evidence_score == 0.88
