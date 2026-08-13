from pathlib import Path

import pytest

from apps.api.services.intent_catalog import IntentCatalog


def test_catalog_is_versioned_and_defines_business_boundaries() -> None:
    catalog = IntentCatalog.from_default_data()

    assert catalog.version
    for intent in ("logistics", "return", "policy", "complaint", "payment_sensitive", "unknown"):
        definition = catalog.get(intent)
        assert definition["description"]
        assert definition["owner"]
        assert "allowed_tools" in definition
        assert "forbidden_tools" in definition
        assert definition["positive_examples"]
        assert definition["hard_negative_examples"]


def test_risk_intent_wins_multi_intent_message_without_losing_secondary_intent() -> None:
    catalog = IntentCatalog.from_default_data()

    decision = catalog.classify("包裹一直没到，我要投诉")

    assert decision["intent"] == "complaint"
    assert "logistics" in decision["secondary_intents"]
    assert decision["risk_labels"] == ["complaint_or_dispute"]


def test_payment_sensitive_has_priority_over_normal_business_intent() -> None:
    catalog = IntentCatalog.from_default_data()

    decision = catalog.classify("先帮我查物流，再修改银行卡收款人")

    assert decision["intent"] == "payment_sensitive"
    assert "logistics" in decision["secondary_intents"]


def test_catalog_distinguishes_generic_policy_from_order_specific_logistics() -> None:
    catalog = IntentCatalog.from_default_data()

    assert catalog.classify("海外仓一般几天送到")["intent"] == "policy"
    assert catalog.classify("我的包裹现在到哪里了")["intent"] == "logistics"


def test_tool_permissions_are_a_catalog_contract() -> None:
    catalog = IntentCatalog.from_default_data()

    assert catalog.is_tool_allowed("logistics", "query_order_logistics")
    assert not catalog.is_tool_allowed("logistics", "submit_return_application")
    assert catalog.is_tool_allowed("payment_sensitive", "create_service_ticket")


def test_invalid_catalog_fails_fast(tmp_path: Path) -> None:
    path = tmp_path / "intents.json"
    path.write_text('{"version":"v1","intents":[]}', encoding="utf-8")

    with pytest.raises(ValueError, match="intent catalog"):
        IntentCatalog.from_path(path)
