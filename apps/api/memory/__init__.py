"""Memory Manager — 统一管理多种 Memory Strategy。

Memory System 设计原则：
1. Memory != RAG（RAG 保存共享知识，Memory 保存用户/会话上下文）
2. Memory != Tool（Tool 提供实时业务事实，Memory 保存历史上下文）
3. 用户显式纠正 > 旧 Memory > 模型推测
4. 不保存全部聊天历史，使用 window + summary
5. 长期 Memory 不替代 Tool 实时事实

三类 Memory：
  - Strategy A: Structured Working Memory（ConversationStore，保留现有）
  - Strategy B: Conversation Memory（Recent Window + Summary）
  - Strategy C: Long-term Memory（Profile + Episodic）
"""

from .manager import MemoryManager
from .store import MemoryStore
from .policy import MemoryWritePolicy, MemoryCandidate
from .retrieval import retrieve_relevant_memory

__all__ = [
    "MemoryManager",
    "MemoryStore",
    "MemoryWritePolicy",
    "MemoryCandidate",
    "retrieve_relevant_memory",
]
