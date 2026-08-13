import json
from pathlib import Path

from apps.api.skills.contracts import SkillManifest


class SkillRegistry:
    def __init__(self, manifests: list[SkillManifest]) -> None:
        if not manifests:
            raise ValueError("skill registry requires at least one manifest")
        self._skills: dict[str, SkillManifest] = {}
        self._by_intent: dict[str, SkillManifest] = {}
        for manifest in manifests:
            if manifest.skill_id in self._skills:
                raise ValueError(f"duplicate skill id: {manifest.skill_id}")
            self._skills[manifest.skill_id] = manifest
            for intent in manifest.trigger_intents:
                if intent in self._by_intent:
                    raise ValueError(f"intent {intent} claimed by multiple skills")
                self._by_intent[intent] = manifest
        required = {"logistics", "return", "policy", "complaint", "payment_sensitive", "unknown"}
        missing = required - set(self._by_intent)
        if missing:
            raise ValueError(f"skill registry missing required intent mappings: {sorted(missing)}")

    @classmethod
    def from_default_manifests(cls) -> "SkillRegistry":
        return cls.from_directory(Path(__file__).parents[3] / "config" / "skills")

    @classmethod
    def from_directory(cls, directory: Path) -> "SkillRegistry":
        manifests = [
            SkillManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))
            for path in sorted(directory.glob("*.json"))
        ]
        return cls(manifests)

    @property
    def skill_ids(self) -> list[str]:
        return sorted(self._skills)

    def get(self, skill_id: str) -> SkillManifest:
        try:
            return self._skills[skill_id]
        except KeyError as exc:
            raise KeyError(f"unknown skill: {skill_id}") from exc

    def for_intent(self, intent: str) -> SkillManifest:
        try:
            return self._by_intent[intent]
        except KeyError as exc:
            raise KeyError(f"no skill registered for intent: {intent}") from exc

