from typing import Any, Callable, Optional

from apps.api.skills.contracts import SkillExecutionContext, SkillHandler, SkillManifest, SkillResult
from apps.api.skills.registry import SkillRegistry
from apps.api.support.responses import ToolResponse


class SkillToolGateway:
    """Enforce a Skill's Tool and confirmation policy at the execution boundary."""

    def __init__(self, manifest: SkillManifest, context: SkillExecutionContext, observability: Any) -> None:
        self.manifest = manifest
        self.context = context
        self.observability = observability
        self.called_tools: list[str] = []
        self.denied_tools: list[str] = []

    def missing_slots(self, values: dict[str, Any]) -> list[str]:
        return [name for name in self.manifest.required_slots if not values.get(name)]

    def call(
        self,
        tool_name: str,
        operation: str,
        callback: Callable[[], ToolResponse],
        *,
        span_name: Optional[str] = None,
        attributes: Optional[dict[str, Any]] = None,
    ) -> ToolResponse:
        if tool_name not in self.manifest.allowed_tools or tool_name in self.manifest.forbidden_tools:
            self.denied_tools.append(tool_name)
            return ToolResponse.failure(
                self.context.trace_id,
                "500_SKILL_TOOL_POLICY_VIOLATION",
                f"Skill {self.manifest.skill_id} 无权调用 Tool {tool_name}，已停止执行。",
                500,
            )
        if operation == "write" and self.manifest.write_confirmation.get(tool_name, False) and not self.context.confirmed:
            self.denied_tools.append(tool_name)
            return ToolResponse.failure(
                self.context.trace_id,
                "409_SKILL_CONFIRMATION_REQUIRED",
                "该写操作需要用户明确确认后才能执行。",
                409,
                handoff=False,
            )
        self.called_tools.append(tool_name)
        span_attributes = {
            "tool.name": tool_name,
            "tool.operation": operation,
            "skill.id": self.manifest.skill_id,
            "skill.version": self.manifest.version,
            **(attributes or {}),
        }
        with self.observability.span(span_name or f"tool.{tool_name}", kind="client", attributes=span_attributes) as tool_span:
            result = callback()
            data = result.data if isinstance(result.data, dict) else {}
            retrieval = data.get("retrieval") or {}
            tool_span.set_result(
                result.success,
                result.error_code,
                candidate_count=retrieval.get("candidate_count"),
                citation_count=len(data.get("citations") or []),
                rerank_score=retrieval.get("rerank_score"),
                embedding_provider=retrieval.get("embedding_provider"),
                reranker_provider=retrieval.get("reranker_provider"),
            )
            return result


class SkillExecutor:
    def __init__(self, registry: SkillRegistry, observability: Any) -> None:
        self.registry = registry
        self.observability = observability

    def execute(self, skill_id: str, context: SkillExecutionContext, handler: SkillHandler) -> SkillResult:
        manifest = self.registry.get(skill_id)
        if context.intent not in manifest.trigger_intents:
            result = ToolResponse.failure(
                context.trace_id,
                "500_SKILL_INTENT_POLICY_VIOLATION",
                f"意图 {context.intent} 不在 Skill {skill_id} 的触发边界内。",
                500,
            )
            return SkillResult.from_tool(skill_id, context.intent, "handoff_human", result, status="failed")
        with self.observability.span(
            f"skill.{skill_id}",
            kind="internal",
            attributes={
                "skill.id": manifest.skill_id,
                "skill.version": manifest.version,
                "skill.phase": context.phase,
                "skill.intent": context.intent,
                "skill.risk_level": manifest.risk_level,
            },
        ) as skill_span:
            gateway = SkillToolGateway(manifest, context, self.observability)
            outcome = handler(context, gateway)
            if outcome.skill_id != skill_id:
                raise ValueError(f"handler returned mismatched skill id: {outcome.skill_id}")
            outcome.skill_version = manifest.version
            if outcome.result.error_code == "500_SKILL_TOOL_POLICY_VIOLATION":
                outcome.status = "failed"
            elif outcome.result.error_code == "409_SKILL_CONFIRMATION_REQUIRED":
                outcome.status = "needs_input"
            controlled = outcome.status in {"completed", "needs_input", "handoff"}
            skill_span.set_result(
                controlled,
                None if controlled else outcome.result.error_code,
                skill_status=outcome.status,
                tool_name=outcome.tool_name,
                called_tools=gateway.called_tools,
                denied_tools=gateway.denied_tools,
                missing_slots=outcome.missing_slots,
            )
            return outcome
