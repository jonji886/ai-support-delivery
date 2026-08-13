from apps.api.services.policy_search import PolicySearchService


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
