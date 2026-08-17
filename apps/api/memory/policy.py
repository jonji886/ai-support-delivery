"""Memory Write Policy — 决定哪些信息值得写入长期 Memory。

流程：
  User Message
    ↓
  Memory Candidate Extraction
    ↓
  Memory Policy（是否值得长期保存？）
    ↓
  Validate（是否稳定事实？）
    ↓
  Conflict Resolution（是否与旧 Memory 冲突？）
    ↓
  Persist / Ignore

优先级：
  User Explicit Correction > Existing Memory > Model Inference

不允许：
  - 无价值闲聊自动成为长期 Memory
  - 模型推测覆盖用户明确事实
  - 临时任务信息写入长期 Memory
"""

import re
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class MemoryCandidate:
    """从用户消息中提取的 Memory 候选。"""

    memory_type: str  # profile | episodic
    key: str
    value: Any
    source: str  # user_explicit | user_correction | model_inference
    confidence: float
    scope: str = "user"
    ttl_minutes: Optional[int] = None
    reason: str = ""


# 稳定偏好关键词模式
_PREFERENCE_PATTERNS = [
    (re.compile(r"(?:以后|以后请|请|希望|喜欢|偏好|习惯)(?:尽量|总是|永远)?(?:用|使用|给|回复|回答)?(简洁|简短|详细|中文|英文|列表|表格)"), "preferred_response_style"),
    (re.compile(r"(?:以后回答|回答)(?:尽量|请)?(简洁|简短|详细|中文|英文)"), "preferred_response_style"),
    (re.compile(r"(?:我习惯|我喜欢|我希望)(?:用|使用)?(中文|英文|繁体|简体)"), "language"),
    (re.compile(r"(?:不要|别)(?:用|使用)(?:表情|emoji|感叹号)"), "preferred_response_style"),
    (re.compile(r"(?:以后|请)(?:都)?(?:直接|直截了当|简短)(?:回答|回复)"), "preferred_response_style"),
]

# 临时信息模式 — 不应写入长期 Memory
_TRANSIENT_PATTERNS = [
    re.compile(r"(?:今天|现在|刚才|刚刚|马上|待会儿)"),
    re.compile(r"(?:天气|温度|几点|几号|星期)"),
    re.compile(r"^(?:好的|嗯|哦|谢谢|知道了|了解|收到|ok|OK|hi|hello|你好)$"),
    re.compile(r"(?:哈哈|呵呵|嘻嘻|哈|嘿)"),
]

# 用户纠正模式
_CORRECTION_PATTERNS = [
    re.compile(r"(?:不是|不对|错了|搞错了|应该是|我说的是|更正是)"),
    re.compile(r"(?:我的订单(?:号)?(?:是|为|改|换成?))"),
]


@dataclass
class MemoryRecord_light:
    """MemoryRecord 的轻量引用，用于冲突解决。"""

    value: Any
    source: str
    confidence: float


@dataclass
class MemoryWritePolicy:
    """Memory 写入策略。"""

    # 已知的稳定偏好 key
    stable_profile_keys: set[str] = field(default_factory=lambda: {
        "preferred_response_style",
        "language",
        "timezone",
        "preferred_contact_method",
    })

    def extract_candidates(
        self,
        message: str,
        *,
        user_id: str,
        existing_profile: dict[str, Any],
    ) -> list[MemoryCandidate]:
        """从用户消息中提取 Memory 候选。

        返回需要写入的候选列表。返回空列表表示不值得写入。
        """
        candidates: list[MemoryCandidate] = []

        # 1. 检查是否是无价值闲聊 — 直接跳过
        if self._is_transient_noise(message):
            return []

        # 2. 检查用户偏好
        for pattern, key in _PREFERENCE_PATTERNS:
            match = pattern.search(message)
            if match:
                value = match.group(1)
                # 检查是否与现有值冲突
                old_value = existing_profile.get(key)
                source = "user_explicit"
                confidence = 1.0
                if old_value and old_value != value:
                    source = "user_correction"
                    confidence = 1.0
                elif old_value == value:
                    # 已存在相同值，不需要写入
                    continue
                candidates.append(MemoryCandidate(
                    memory_type="profile",
                    key=key,
                    value=value,
                    source=source,
                    confidence=confidence,
                    reason=f"用户明确表达偏好: {key}={value}",
                ))

        # 3. 检查用户纠正 — 订单号纠正等
        for pattern in _CORRECTION_PATTERNS:
            if pattern.search(message):
                # 订单纠正由 Working Memory（ConversationStore）处理，这里不重复
                # 但如果纠正的是偏好，上面已经捕获
                break

        return candidates

    def _is_transient_noise(self, message: str) -> bool:
        """判断消息是否是无价值闲聊。"""
        stripped = message.strip()
        if not stripped or len(stripped) < 2:
            return True
        for pattern in _TRANSIENT_PATTERNS:
            if pattern.search(stripped):
                return True
        return False

    def should_persist(self, candidate: MemoryCandidate) -> bool:
        """决定 Memory 候选是否应该持久化。"""
        # 用户显式表达或纠正 — 总是持久化
        if candidate.source in ("user_explicit", "user_correction"):
            return True
        # 模型推测 — 仅持久化稳定偏好，不持久化临时信息
        if candidate.source == "model_inference":
            return candidate.key in self.stable_profile_keys and candidate.confidence >= 0.7
        return False

    def resolve_conflict(
        self,
        candidate: MemoryCandidate,
        existing: Optional[MemoryRecord_light],
    ) -> tuple[bool, str]:
        """冲突解决。

        返回 (should_write, reason)。
        优先级：User Explicit Correction > Existing Memory > Model Inference
        """
        if existing is None:
            return (True, "无冲突，直接写入")

        # 用户显式纠正 — 总是覆盖
        if candidate.source == "user_correction":
            return (True, "用户显式纠正，覆盖旧值")

        # 用户显式表达且值不同 — 覆盖
        if candidate.source == "user_explicit" and existing.value != candidate.value:
            return (True, "用户新偏好，覆盖旧值")

        # 模型推测 vs 已有用户明确值 — 不覆盖
        if candidate.source == "model_inference" and existing.source in ("user_explicit", "user_correction"):
            return (False, "模型推测不得覆盖用户明确事实")

        # 值相同 — 不需要写入
        if existing.value == candidate.value:
            return (False, "值相同，无需更新")

        return (True, "无冲突，写入")
