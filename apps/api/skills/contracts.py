from typing import Any, Callable, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from apps.api.support.responses import ToolResponse


class SkillEvaluationContract(BaseModel):
    dataset: str
    release_gates: dict[str, float]


class SkillManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    display_name: str
    description: str
    owner: str
    trigger_intents: list[str]
    positive_examples: list[str]
    hard_negative_examples: list[str]
    required_slots: list[str]
    optional_slots: list[str] = Field(default_factory=list)
    allowed_tools: list[str]
    forbidden_tools: list[str]
    risk_level: str
    phases: list[str]
    write_confirmation: dict[str, bool] = Field(default_factory=dict)
    handoff_conditions: list[str]
    output_contract: list[str]
    evaluation: SkillEvaluationContract

    @model_validator(mode="after")
    def validate_boundaries(self) -> "SkillManifest":
        if not self.trigger_intents or not self.positive_examples or not self.hard_negative_examples:
            raise ValueError("skill requires trigger intents, positive examples and hard negatives")
        overlap = set(self.allowed_tools) & set(self.forbidden_tools)
        if overlap:
            raise ValueError(f"allowed_tools and forbidden_tools overlap: {sorted(overlap)}")
        unknown_confirmation = set(self.write_confirmation) - set(self.allowed_tools)
        if unknown_confirmation:
            raise ValueError(f"write confirmation references unauthorized tools: {sorted(unknown_confirmation)}")
        if not self.phases or not self.output_contract or not self.owner:
            raise ValueError("skill requires phases, output contract and owner")
        return self


class SkillExecutionContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    trace_id: str
    intent: str
    phase: str = "execute"
    confirmed: bool = False
    payload: dict[str, Any] = Field(default_factory=dict)


class SkillResult(BaseModel):
    skill_id: str
    skill_version: Optional[str] = None
    status: Literal["completed", "needs_input", "handoff", "failed"]
    intent: str
    tool_name: str
    result: ToolResponse
    missing_slots: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    session_values: dict[str, Any] = Field(default_factory=dict)
    record_conversation: bool = True

    @classmethod
    def from_tool(
        cls,
        skill_id: str,
        intent: str,
        tool_name: str,
        result: ToolResponse,
        *,
        status: Optional[Literal["completed", "needs_input", "handoff", "failed"]] = None,
        **kwargs: Any,
    ) -> "SkillResult":
        resolved_status = status or ("handoff" if result.handoff else "completed" if result.success else "failed")
        return cls(
            skill_id=skill_id,
            intent=intent,
            tool_name=tool_name,
            result=result,
            status=resolved_status,
            **kwargs,
        )


SkillHandler = Callable[[SkillExecutionContext, Any], SkillResult]
