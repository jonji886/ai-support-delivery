"""Memory Retrieval — 根据上下文选择有限 Memory。

不将全部 Memory 塞给模型，而是根据：
  - user
  - session
  - current intent
  - current order
  - recency
  - memory type
  - relevance

构建 Context Builder 输出：
  Current Request
  + Structured Business State (Working Memory)
  + Recent Conversation (Conversation Memory window)
  + Conversation Summary
  + Relevant Long-term Memory (Profile + Episodic)
  + Retrieved Knowledge (RAG, 由外部注入)
  + Tool Result (由外部注入)
"""

from typing import Any, Optional

from .store import MemoryStore


def retrieve_relevant_memory(
    *,
    store: MemoryStore,
    user_id: str,
    session_id: Optional[str] = None,
    current_intent: Optional[str] = None,
    current_order_id: Optional[str] = None,
    conversation_window_size: int = 10,
    include_profile: bool = True,
    include_episodic: bool = True,
) -> dict[str, Any]:
    """检索与当前请求相关的 Memory。

    返回结构化 Memory Context，供 Agent 使用。
    """
    context: dict[str, Any] = {}

    # 1. Conversation Memory: 最近对话窗口
    if session_id:
        messages = store.get_conversation_window(
            session_id=session_id,
            user_id=user_id,
            window_size=conversation_window_size,
        )
        if messages:
            context["conversation_window"] = messages

        # 2. Conversation Summary
        summary = store.get_conversation_summary(
            session_id=session_id,
            user_id=user_id,
        )
        if summary:
            context["conversation_summary"] = summary

    # 3. Long-term Memory: Profile
    if include_profile:
        profile_records = store.get_active(
            user_id=user_id,
            memory_type="profile",
        )
        if profile_records:
            context["user_profile"] = {
                r.key: {
                    "value": r.value,
                    "source": r.source,
                    "confidence": r.confidence,
                    "updated_at": r.updated_at,
                }
                for r in profile_records
            }

    # 4. Long-term Memory: Episodic
    if include_episodic:
        episodic_records = store.get_active(
            user_id=user_id,
            memory_type="episodic",
        )
        if episodic_records:
            context["episodic_memory"] = [
                {
                    "key": r.key,
                    "value": r.value,
                    "source": r.source,
                    "created_at": r.created_at,
                }
                for r in episodic_records
            ]

    # 5. 根据 intent 和 order 过滤相关性
    if current_order_id:
        # 如果有当前订单，标记订单相关的 episodic
        episodic = context.get("episodic_memory", [])
        context["order_related_episodic"] = [
            e for e in episodic
            if isinstance(e["value"], dict) and e["value"].get("order_id") == current_order_id
        ]

    return context


def build_context_for_prompt(
    memory_context: dict[str, Any],
    *,
    max_messages: int = 6,
    max_episodic: int = 3,
) -> str:
    """将 Memory Context 格式化为 Prompt 友好的字符串。

    用于注入 LLM Prompt 的语言上下文部分。
    """
    parts: list[str] = []

    # User Profile
    profile = memory_context.get("user_profile")
    if profile:
        pref_str = "; ".join(f"{k}={v['value']}" for k, v in profile.items())
        parts.append(f"[User Profile] {pref_str}")

    # Conversation Summary
    summary = memory_context.get("conversation_summary")
    if summary:
        parts.append(f"[Previous Conversation Summary] {summary}")

    # Conversation Window
    messages = memory_context.get("conversation_window", [])
    if messages:
        recent = messages[-max_messages:]
        msg_str = "\n".join(f"  {m['role']}: {m['content']}" for m in recent)
        parts.append(f"[Recent Conversation]\n{msg_str}")

    # Episodic Memory
    episodic = memory_context.get("order_related_episodic") or memory_context.get("episodic_memory", [])
    if episodic:
        recent_episodic = episodic[-max_episodic:]
        ep_str = "; ".join(
            f"{e['key']}: {e['value'] if isinstance(e['value'], str) else e['value'].get('summary', e['value'])}"
            for e in recent_episodic
        )
        parts.append(f"[Episodic Memory] {ep_str}")

    if not parts:
        return ""

    return "\n\n".join(parts)
