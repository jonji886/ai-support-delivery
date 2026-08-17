"""MemoryManager — 统一管理多种 Memory Strategy。

职责：
  1. 包装 ConversationStore（Working Memory，保留现有）
  2. 管理 Conversation Memory（window + summary）
  3. 管理 Long-term Memory（profile + episodic）
  4. 执行 Memory Write Policy
  5. 提供 retrieve_relevant_memory 统一接口
  6. 提供 Memory Inspector 查询接口

不职责：
  - 不替代 RAG（RAG 保存共享知识）
  - 不替代 Tool（Tool 提供实时事实）
  - 不管理 LangGraph State（LangGraph 自己管）
"""

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from .store import MemoryStore, MemoryRecord
from .policy import MemoryWritePolicy, MemoryCandidate, MemoryRecord_light
from .retrieval import retrieve_relevant_memory, build_context_for_prompt

logger = logging.getLogger(__name__)


class MemoryManager:
    """统一 Memory 管理入口。"""

    def __init__(
        self,
        *,
        conversation_store: Any,  # ConversationStore (Working Memory)
        memory_store: Optional[MemoryStore] = None,
        write_policy: Optional[MemoryWritePolicy] = None,
        clock: Optional[Callable[[], datetime]] = None,
        conversation_window_size: int = 10,
        summary_trigger_messages: int = 8,
    ) -> None:
        self.conversation_store = conversation_store
        self.memory_store = memory_store or MemoryStore(clock=clock)
        self.write_policy = write_policy or MemoryWritePolicy()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.conversation_window_size = conversation_window_size
        self.summary_trigger_messages = summary_trigger_messages

    # --- Working Memory（委托给 ConversationStore）---

    def get_working_memory(self, session_id: Optional[str], user_id: Optional[str] = None) -> Optional[dict[str, Any]]:
        """获取 Working Memory（结构化业务状态）。"""
        return self.conversation_store.get(session_id, user_id)

    def save_working_memory(self, session_id: Optional[str], **kwargs: Any) -> None:
        """保存 Working Memory（委托给 ConversationStore.save）。"""
        self.conversation_store.save(session_id, **kwargs)

    def session_belongs_to_other_user(self, session_id: Optional[str], user_id: Optional[str]) -> bool:
        """检查会话是否属于其他用户（用户隔离）。"""
        return self.conversation_store.session_belongs_to_other_user(session_id, user_id)

    # --- Conversation Memory ---

    def record_conversation_message(
        self,
        *,
        user_id: str,
        session_id: str,
        role: str,
        content: str,
    ) -> None:
        """记录对话消息到 Conversation Memory。"""
        self.memory_store.add_conversation_message(
            user_id=user_id,
            session_id=session_id,
            role=role,
            content=content,
        )

        # 检查是否需要触发摘要
        self._maybe_summarize(user_id=user_id, session_id=session_id)

    def get_conversation_window(self, *, session_id: str, user_id: str) -> list[dict[str, Any]]:
        """获取会话最近对话窗口。"""
        return self.memory_store.get_conversation_window(
            session_id=session_id,
            user_id=user_id,
            window_size=self.conversation_window_size,
        )

    def _maybe_summarize(self, *, user_id: str, session_id: str) -> None:
        """当对话消息数超过阈值时触发摘要。

        注意：真正的摘要需要 LLM。这里只做简单的最近消息拼接。
        生产环境应注入 LLM Provider。
        """
        messages = self.memory_store.get_conversation_window(
            session_id=session_id,
            user_id=user_id,
            window_size=100,  # 获取全部消息检查数量
        )
        if len(messages) >= self.summary_trigger_messages:
            # 检查是否已有摘要
            existing = self.memory_store.get_conversation_summary(
                session_id=session_id,
                user_id=user_id,
            )
            if not existing:
                # 简单摘要：取前几条消息的关键信息
                summary_parts = [f"{m['role']}: {m['content'][:50]}" for m in messages[:5]]
                summary = f"会话历史摘要({len(messages)}条消息): " + " | ".join(summary_parts)
                self.memory_store.save_conversation_summary(
                    user_id=user_id,
                    session_id=session_id,
                    summary=summary,
                    message_count=len(messages),
                )

    # --- Long-term Memory ---

    def process_user_message(
        self,
        message: str,
        *,
        user_id: str,
        session_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """处理用户消息，提取并写入长期 Memory。

        返回写入的 Memory 记录列表（用于调试/Inspector）。
        """
        # 获取现有 profile
        existing_profile_records = self.memory_store.get_active(
            user_id=user_id,
            memory_type="profile",
        )
        existing_profile = {r.key: r.value for r in existing_profile_records}

        # 提取候选
        candidates = self.write_policy.extract_candidates(
            message,
            user_id=user_id,
            existing_profile=existing_profile,
        )

        written: list[dict[str, Any]] = []
        for candidate in candidates:
            if not self.write_policy.should_persist(candidate):
                continue

            # 检查冲突
            existing_records = self.memory_store.get_active(
                user_id=user_id,
                memory_type=candidate.memory_type,
                key=candidate.key,
            )
            existing = existing_records[0] if existing_records else None

            # 构建轻量引用
            existing_ref = MemoryRecord_light(
                value=existing.value,
                source=existing.source,
                confidence=existing.confidence,
            ) if existing else None

            should_write, reason = self.write_policy.resolve_conflict(candidate, existing_ref)
            if not should_write:
                logger.debug("Memory write skipped: %s (reason: %s)", candidate.key, reason)
                continue

            # 写入
            memory_id = self.memory_store.upsert(
                user_id=user_id,
                memory_type=candidate.memory_type,
                key=candidate.key,
                value=candidate.value,
                source=candidate.source,
                confidence=candidate.confidence,
                scope=candidate.scope,
                session_id=session_id,
                ttl_minutes=candidate.ttl_minutes,
            )
            written.append({
                "memory_id": memory_id,
                "type": candidate.memory_type,
                "key": candidate.key,
                "value": candidate.value,
                "source": candidate.source,
                "reason": reason,
            })

        return written

    def record_episodic(
        self,
        *,
        user_id: str,
        key: str,
        value: dict[str, Any],
        source: str = "system_event",
        confidence: float = 0.90,
    ) -> str:
        """记录历史事件到 Episodic Memory。

        例如：人工接管摘要、已解决问题摘要。
        """
        return self.memory_store.upsert(
            user_id=user_id,
            memory_type="episodic",
            key=key,
            value=value,
            source=source,
            confidence=confidence,
            scope="user",
        )

    # --- Retrieval ---

    def retrieve_context(
        self,
        *,
        user_id: str,
        session_id: Optional[str] = None,
        current_intent: Optional[str] = None,
        current_order_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """检索与当前请求相关的 Memory Context。"""
        context = retrieve_relevant_memory(
            store=self.memory_store,
            user_id=user_id,
            session_id=session_id,
            current_intent=current_intent,
            current_order_id=current_order_id,
            conversation_window_size=self.conversation_window_size,
        )
        return context

    def build_prompt_context(self, memory_context: dict[str, Any]) -> str:
        """将 Memory Context 格式化为 Prompt 字符串。"""
        return build_context_for_prompt(memory_context)

    # --- Memory Inspector ---

    def list_memory(
        self,
        user_id: str,
        *,
        memory_type: Optional[str] = None,
    ) -> list[MemoryRecord]:
        """列出用户的所有 Memory（用于 Inspector）。"""
        return self.memory_store.list_by_user(
            user_id,
            memory_type=memory_type,
            active_only=False,  # Inspector 显示全部
        )

    # --- Maintenance ---

    def purge_expired(self) -> dict[str, int]:
        """清理过期 Memory。"""
        working = self.conversation_store.purge_expired()
        long_term = self.memory_store.purge_expired()
        return {"working_memory": working, "long_term_memory": long_term}
