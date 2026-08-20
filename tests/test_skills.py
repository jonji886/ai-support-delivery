import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.skills.contracts import SkillExecutionContext, SkillResult
from apps.api.skills.executor import SkillExecutor
from apps.api.skills.registry import SkillRegistry
from apps.api.support.responses import ToolResponse


client = TestClient(app)


class NoopObservability:
    class Span:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def set_attributes(self, **kwargs):
            pass

        def set_result(self, *args, **kwargs):
            pass

    def span(self, *args, **kwargs):
        return self.Span()


def test_registry_loads_versioned_scenario_skills_and_intent_mapping() -> None:
    registry = SkillRegistry.from_default_manifests()

    assert set(registry.skill_ids) == {
        "logistics_inquiry", "return_resolution", "policy_qa", "risk_handoff",
    }
    assert registry.for_intent("logistics").skill_id == "logistics_inquiry"
    assert registry.for_intent("return").skill_id == "return_resolution"
    assert registry.for_intent("complaint").skill_id == "risk_handoff"
    assert registry.for_intent("payment_sensitive").skill_id == "risk_handoff"
    assert registry.for_intent("unknown").skill_id == "risk_handoff"


def test_return_skill_is_more_than_a_tool_and_governs_two_stage_write() -> None:
    manifest = SkillRegistry.from_default_manifests().get("return_resolution")

    assert manifest.required_slots == ["user_id", "order_id", "return_reason"]
    assert "check_return_eligibility" in manifest.allowed_tools
    assert "submit_return_application" in manifest.allowed_tools
    assert manifest.write_confirmation["submit_return_application"] is True
    assert manifest.handoff_conditions
    assert manifest.evaluation.release_gates["unauthorized_tool_calls"] == 0
    assert Path(manifest.evaluation.dataset).exists()
    assert set(manifest.output_contract) <= set(SkillResult.model_fields)


def test_registry_rejects_two_skills_claiming_the_same_intent(tmp_path: Path) -> None:
    source = Path("config/skills/logistics-inquiry.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    duplicate = {**payload, "skill_id": "duplicate_logistics", "version": "1.0.0"}
    (tmp_path / "first.json").write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "second.json").write_text(json.dumps(duplicate), encoding="utf-8")

    with pytest.raises(ValueError, match="claimed by multiple skills"):
        SkillRegistry.from_directory(tmp_path)


def test_executor_blocks_unauthorized_tool_before_callback() -> None:
    executor = SkillExecutor(SkillRegistry.from_default_manifests(), NoopObservability())
    callback_called = [False]

    def handler(context, tools):
        def callback():
            callback_called[0] = True
            return ToolResponse.success_result({}, context.trace_id, "不应执行")

        result = tools.call("submit_return_application", "write", callback)
        return SkillResult.from_tool("logistics_inquiry", "logistics", "submit_return_application", result)

    outcome = executor.execute(
        "logistics_inquiry",
        SkillExecutionContext(trace_id="trace-unauthorized", intent="logistics"),
        handler,
    )

    assert callback_called[0] is False
    assert outcome.result.error_code == "500_SKILL_TOOL_POLICY_VIOLATION"


def test_executor_blocks_write_without_explicit_confirmation() -> None:
    executor = SkillExecutor(SkillRegistry.from_default_manifests(), NoopObservability())
    callback_called = [False]

    def handler(context, tools):
        def callback():
            callback_called[0] = True
            return ToolResponse.success_result({}, context.trace_id, "不应执行")

        result = tools.call("submit_return_application", "write", callback)
        return SkillResult.from_tool("return_resolution", "return", "submit_return_application", result)

    outcome = executor.execute(
        "return_resolution",
        SkillExecutionContext(trace_id="trace-unconfirmed", intent="return"),
        handler,
    )

    assert callback_called[0] is False
    assert outcome.result.error_code == "409_SKILL_CONFIRMATION_REQUIRED"


def test_assist_trace_exposes_selected_skill_and_nested_tool() -> None:
    response = client.post(
        "/assist",
        json={"message": "帮我查下包裹", "order_id": "OD202608001"},
        headers={"X-User-Id": "user-demo-001"},
    )
    replay = client.get(
        f"/admin/traces/{response.json()['trace_id']}", headers={"X-Role": "supervisor"},
    ).json()
    spans = {span["name"]: span for span in replay["spans"]}

    assert spans["skill.logistics_inquiry"]["attributes"]["skill.version"] == "1.0.0"
    assert spans["tool.query_order_logistics"]["parent_span_id"] == spans["skill.logistics_inquiry"]["span_id"]


def test_confirmed_return_submission_runs_inside_return_skill() -> None:
    response = client.post(
        "/tools/submit-return-application",
        json={
            "order_id": "OD202608001", "return_reason": "尺码不合适",
            "idempotency_key": "skill-confirmed-return-01",
        },
        headers={"X-User-Id": "user-demo-001"},
    )
    replay = client.get(
        f"/admin/traces/{response.json()['trace_id']}", headers={"X-Role": "supervisor"},
    ).json()

    assert response.status_code == 200
    assert any(
        span["name"] == "skill.return_resolution"
        and span["attributes"]["skill.phase"] == "confirm_submit"
        for span in replay["spans"]
    )


def test_return_handoff_is_not_saved_as_resolved_session() -> None:
    from apps.api.main import conversations

    session_id = "skill-return-handoff-" + uuid4().hex
    response = client.post(
        "/assist",
        json={
            "message": "我想退货，原因：商品质量问题",
            "order_id": "OD202608001",
            "session_id": session_id,
        },
        headers={"X-User-Id": "user-demo-001"},
    )
    session = conversations.get(session_id, "user-demo-001")

    assert response.status_code == 200
    assert response.json()["handoff"] is True
    assert session is not None
    assert session["unresolved_count"] == 1
