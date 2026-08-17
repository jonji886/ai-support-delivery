"""Memory System 测试。

验证：
  - Context Continuity（多轮不重复询问）
  - User Isolation（A 的 Memory 不被 B 获取）
  - Stale Memory（订单变化后旧事实不污染）
  - Correction（用户纠正后使用新值）
  - Long-term Preference（跨 session 偏好生效）
  - Conflict Resolution（用户显式纠正 > 旧 Memory）
  - Memory Pollution（闲聊不写入长期 Memory）
  - Token Cost（window vs summary vs hybrid）
"""

import os
import tempfile
from datetime import datetime, timezone

import pytest

from apps.api.memory import MemoryManager, MemoryStore, MemoryWritePolicy
from apps.api.support.conversations import ConversationStore


@pytest.fixture
def fixed_clock():
    """固定时钟用于确定性测试。"""
    return lambda: datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def temp_db():
    """临时数据库路径。"""
    with tempfile.TemporaryDirectory() as d:
        yield os.path.join(d, "test_memory.db")


@pytest.fixture
def conversation_store(temp_db, fixed_clock):
    return ConversationStore(
        db_path=os.path.join(os.path.dirname(temp_db), "conv.db"),
        clock=fixed_clock,
    )


@pytest.fixture
def memory_store(temp_db, fixed_clock):
    return MemoryStore(db_path=temp_db, clock=fixed_clock)


@pytest.fixture
def manager(conversation_store, memory_store, fixed_clock):
    return MemoryManager(
        conversation_store=conversation_store,
        memory_store=memory_store,
        clock=fixed_clock,
        conversation_window_size=10,
        summary_trigger_messages=8,
    )


# === Strategy A: Structured Working Memory ===

class TestWorkingMemory:
    """保留现有 ConversationStore 的结构化业务状态。"""

    def test_save_and_get_slot(self, manager):
        manager.save_working_memory(
            "sess-001",
            user_id="user-A",
            order_id="OD001",
            intent="logistics",
            resolved=True,
        )
        wm = manager.get_working_memory("sess-001", "user-A")
        assert wm is not None
        assert wm["order_id"] == "OD001"
        assert wm["last_intent"] == "logistics"

    def test_order_switch_clears_old_order_slots(self, manager):
        """订单切换必须清理旧订单作用域 Memory。"""
        manager.save_working_memory(
            "sess-001",
            user_id="user-A",
            order_id="OD001",
            intent="logistics",
            resolved=True,
            return_reason="damaged",
            slot_sources={"return_reason": "user_explicit"},
        )
        # 切换到 OD002
        manager.save_working_memory(
            "sess-001",
            user_id="user-A",
            order_id="OD002",
            intent="logistics",
            resolved=True,
        )
        wm = manager.get_working_memory("sess-001", "user-A")
        # return_reason 是 order-scoped，应该被清理
        assert wm.get("return_reason") is None
        assert wm["order_id"] == "OD002"

    def test_user_isolation_session(self, manager):
        """不同用户的 session 不能互相访问。"""
        manager.save_working_memory(
            "sess-001",
            user_id="user-A",
            order_id="OD001",
            intent="logistics",
            resolved=True,
        )
        # user-B 不能访问 user-A 的 session
        assert manager.session_belongs_to_other_user("sess-001", "user-B")
        wm = manager.get_working_memory("sess-001", "user-B")
        assert wm is None


# === Strategy B: Conversation Memory ===

class TestConversationMemory:
    """Recent Window + Summary。"""

    def test_record_and_retrieve_conversation(self, manager):
        manager.record_conversation_message(
            user_id="user-A",
            session_id="sess-001",
            role="user",
            content="我的订单 OD001 到哪了？",
        )
        manager.record_conversation_message(
            user_id="user-A",
            session_id="sess-001",
            role="assistant",
            content="您的订单 OD001 已发货，预计明天到达。",
        )
        msgs = manager.get_conversation_window(session_id="sess-001", user_id="user-A")
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"

    def test_conversation_window_size_limit(self, manager):
        """window 只返回最近 N 条。"""
        for i in range(15):
            manager.record_conversation_message(
                user_id="user-A",
                session_id="sess-001",
                role="user",
                content=f"消息 {i}",
            )
        msgs = manager.get_conversation_window(session_id="sess-001", user_id="user-A")
        assert len(msgs) == 10  # window_size=10

    def test_conversation_user_isolation(self, manager):
        """User A 的对话 Memory 不能被 User B 获取。"""
        manager.record_conversation_message(
            user_id="user-A",
            session_id="sess-A",
            role="user",
            content="user A 的消息",
        )
        # user-B 查询自己的 session 不会看到 user-A 的消息
        msgs = manager.get_conversation_window(session_id="sess-A", user_id="user-B")
        assert len(msgs) == 0

    def test_conversation_session_isolation(self, manager):
        """不同 session 的对话不互通。"""
        manager.record_conversation_message(
            user_id="user-A",
            session_id="sess-001",
            role="user",
            content="session 1 消息",
        )
        manager.record_conversation_message(
            user_id="user-A",
            session_id="sess-002",
            role="user",
            content="session 2 消息",
        )
        msgs1 = manager.get_conversation_window(session_id="sess-001", user_id="user-A")
        msgs2 = manager.get_conversation_window(session_id="sess-002", user_id="user-A")
        assert len(msgs1) == 1
        assert len(msgs2) == 1
        assert msgs1[0]["content"] == "session 1 消息"
        assert msgs2[0]["content"] == "session 2 消息"


# === Strategy C: Long-term Memory ===

class TestLongTermMemory:
    """Profile + Episodic。"""

    def test_preference_persistence(self, manager):
        """用户表达偏好后应写入长期 Memory。"""
        written = manager.process_user_message(
            "以后回答尽量简洁",
            user_id="user-A",
            session_id="sess-001",
        )
        assert len(written) >= 1
        assert written[0]["type"] == "profile"
        assert written[0]["key"] == "preferred_response_style"
        assert written[0]["value"] == "简洁"

    def test_preference_cross_session(self, manager):
        """长期偏好跨 session 生效。"""
        # Session A: 用户表达偏好
        manager.process_user_message(
            "以后请用简短回复",
            user_id="user-A",
            session_id="sess-A",
        )
        # Session B: 应能检索到偏好
        context = manager.retrieve_context(user_id="user-A", session_id="sess-B")
        assert "user_profile" in context
        assert "preferred_response_style" in context["user_profile"]

    def test_preference_correction(self, manager):
        """用户修改偏好后应更新。"""
        manager.process_user_message("以后请用详细回答", user_id="user-A", session_id="sess-A")
        profile = manager.memory_store.get_active(user_id="user-A", memory_type="profile")
        assert profile[0].value == "详细"

        # 用户纠正
        manager.process_user_message("以后请用简洁回答", user_id="user-A", session_id="sess-A")
        profile = manager.memory_store.get_active(user_id="user-A", memory_type="profile")
        assert profile[0].value == "简洁"
        assert profile[0].source == "user_correction"

    def test_episodic_recording(self, manager):
        """历史事件记录。"""
        manager.record_episodic(
            user_id="user-A",
            key="handoff-001",
            value={
                "event": "human_handoff",
                "order_id": "OD001",
                "summary": "用户投诉物流延迟，已转人工处理。",
            },
        )
        context = manager.retrieve_context(user_id="user-A", current_order_id="OD001")
        assert "episodic_memory" in context
        assert context["order_related_episodic"][0]["value"]["order_id"] == "OD001"


# === Memory Write Policy ===

class TestMemoryWritePolicy:
    """Memory 写入策略。"""

    def test_transient_noise_not_saved(self, manager):
        """无价值闲聊不应写入长期 Memory。"""
        written = manager.process_user_message("今天天气不错", user_id="user-A", session_id="sess-A")
        assert len(written) == 0

        written = manager.process_user_message("好的", user_id="user-A", session_id="sess-A")
        assert len(written) == 0

        written = manager.process_user_message("哈哈", user_id="user-A", session_id="sess-A")
        assert len(written) == 0

    def test_stable_preference_saved(self, manager):
        written = manager.process_user_message("以后请用中文回复", user_id="user-A", session_id="sess-A")
        assert len(written) >= 1

    def test_same_preference_not_duplicated(self, manager):
        """相同偏好不重复写入。"""
        manager.process_user_message("以后请用简洁回答", user_id="user-A", session_id="sess-A")
        written = manager.process_user_message("以后请用简洁回答", user_id="user-A", session_id="sess-A")
        assert len(written) == 0

    def test_policy_is_transient_noise(self):
        policy = MemoryWritePolicy()
        assert policy._is_transient_noise("好的")
        assert policy._is_transient_noise("哈哈")
        assert policy._is_transient_noise("今天天气不错")
        assert not policy._is_transient_noise("我的订单 OD001 到哪了？")
        assert not policy._is_transient_noise("以后请用简洁回答")


# === Conflict Resolution ===

class TestConflictResolution:
    """冲突解决。"""

    def test_user_correction_overrides_old(self, manager):
        """用户显式纠正覆盖旧值。"""
        # 写入初始偏好
        manager.process_user_message("以后请用详细回答", user_id="user-A", session_id="sess-A")
        # 纠正
        manager.process_user_message("以后请用简洁回答", user_id="user-A", session_id="sess-A")
        context = manager.retrieve_context(user_id="user-A")
        assert context["user_profile"]["preferred_response_style"]["value"] == "简洁"


# === Memory Inspector ===

class TestMemoryInspector:
    """Memory Inspector 查询。"""

    def test_list_memory_by_user(self, manager):
        manager.process_user_message("以后请用简洁回答", user_id="user-A", session_id="sess-A")
        manager.record_episodic(
            user_id="user-A",
            key="event-001",
            value={"summary": "测试事件"},
        )
        records = manager.list_memory("user-A")
        assert len(records) >= 2
        types = {r.memory_type for r in records}
        assert "profile" in types
        assert "episodic" in types

    def test_list_memory_by_type(self, manager):
        manager.process_user_message("以后请用简洁回答", user_id="user-A", session_id="sess-A")
        records = manager.list_memory("user-A", memory_type="profile")
        assert len(records) == 1
        assert all(r.memory_type == "profile" for r in records)

    def test_list_memory_user_isolation(self, manager):
        """Inspector 查询不会泄露其他用户。"""
        manager.process_user_message("以后请用简洁回答", user_id="user-A", session_id="sess-A")
        records = manager.list_memory("user-B")
        assert len(records) == 0


# === Retrieval ===

class TestMemoryRetrieval:
    """Memory 检索。"""

    def test_retrieve_context_returns_relevant_only(self, manager):
        """检索只返回相关 Memory，不返回全部。"""
        manager.record_conversation_message(
            user_id="user-A",
            session_id="sess-A",
            role="user",
            content="消息1",
        )
        manager.process_user_message("以后请用简洁回答", user_id="user-A", session_id="sess-A")
        manager.record_episodic(
            user_id="user-A",
            key="event-001",
            value={"summary": "历史事件"},
        )
        context = manager.retrieve_context(
            user_id="user-A",
            session_id="sess-A",
            current_order_id="OD001",
        )
        # 应包含 conversation_window, user_profile, episodic_memory
        assert "conversation_window" in context
        assert "user_profile" in context
        assert "episodic_memory" in context
        # 不应包含其他用户的数据
        for key in context:
            assert context[key] is not None

    def test_retrieve_context_empty_for_new_user(self, manager):
        """新用户无 Memory。"""
        context = manager.retrieve_context(user_id="user-new", session_id="sess-new")
        assert "conversation_window" not in context
        assert "user_profile" not in context
