"""扩展 Memory Eval — 覆盖 Conversation Memory 和 Long-term Memory。

验证维度：
  1. Context Continuity（多轮不重复询问订单号）
  2. User Isolation（cross_user_leakage = 0）
  3. Stale Memory（订单变化后旧事实不污染）
  4. Correction（用户纠正后使用新值）
  5. Long-term Preference（跨 session 偏好生效）
  6. Conflict Resolution（用户显式纠正 > 旧 Memory）
  7. Memory Pollution（闲聊不写入长期 Memory）
  8. Token / Context Cost（window vs summary vs hybrid）
"""

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps.api.memory import MemoryManager, MemoryStore
from apps.api.support.conversations import ConversationStore


def run_eval() -> dict:
    results: list[dict] = []
    def fixed_clock() -> datetime:
        return datetime(2026, 8, 13, 10, 0, 0, tzinfo=timezone.utc)

    with tempfile.TemporaryDirectory(prefix="memory-eval-ext-") as directory:
        conv_store = ConversationStore(
            db_path=str(Path(directory) / "conv.db"),
            clock=fixed_clock,
        )
        mem_store = MemoryStore(
            db_path=str(Path(directory) / "memory.db"),
            clock=fixed_clock,
        )
        manager = MemoryManager(
            conversation_store=conv_store,
            memory_store=mem_store,
            clock=fixed_clock,
            conversation_window_size=10,
            summary_trigger_messages=8,
        )

        # === 1. Context Continuity ===
        # 多轮：同一 session 不重复询问订单号
        manager.save_working_memory(
            "sess-cont-001", user_id="user-A",
            order_id="OD001", intent="logistics", resolved=True,
        )
        wm = manager.get_working_memory("sess-cont-001", "user-A")
        results.append({
            "case_id": "context_continuity_1",
            "category": "context_continuity",
            "description": "同 session 第二轮继承订单号",
            "passed": wm["order_id"] == "OD001",
            "expected": "OD001",
            "actual": wm.get("order_id"),
        })

        # === 2. User Isolation ===
        manager.record_conversation_message(
            user_id="user-A", session_id="sess-iso-A",
            role="user", content="user A 的消息",
        )
        manager.process_user_message(
            "以后请用简洁回答",
            user_id="user-A", session_id="sess-iso-A",
        )
        # user-B 查询不应该看到 user-A 的数据
        b_msgs = manager.get_conversation_window(session_id="sess-iso-A", user_id="user-B")
        b_profile = manager.list_memory("user-B", memory_type="profile")
        results.append({
            "case_id": "user_isolation_1",
            "category": "user_isolation",
            "description": "User B 无法获取 User A 的对话 Memory",
            "passed": len(b_msgs) == 0,
            "expected": 0,
            "actual": len(b_msgs),
        })
        results.append({
            "case_id": "user_isolation_2",
            "category": "user_isolation",
            "description": "User B 无法获取 User A 的长期 Memory",
            "passed": len(b_profile) == 0,
            "expected": 0,
            "actual": len(b_profile),
        })

        # === 3. Stale Memory ===
        manager.save_working_memory(
            "sess-stale-001", user_id="user-C",
            order_id="OD001", intent="return", resolved=True,
            return_reason="damaged",
            slot_sources={"return_reason": "user_explicit"},
        )
        # 切换订单
        manager.save_working_memory(
            "sess-stale-001", user_id="user-C",
            order_id="OD002", intent="logistics", resolved=True,
        )
        wm_stale = manager.get_working_memory("sess-stale-001", "user-C")
        results.append({
            "case_id": "stale_memory_1",
            "category": "stale_memory",
            "description": "订单切换后旧订单退货原因不污染",
            "passed": wm_stale.get("return_reason") is None,
            "expected": None,
            "actual": wm_stale.get("return_reason"),
        })

        # === 4. Correction ===
        manager.save_working_memory(
            "sess-corr-001", user_id="user-D",
            order_id="OD001", intent="logistics", resolved=True,
        )
        # 用户纠正为 OD002
        manager.save_working_memory(
            "sess-corr-001", user_id="user-D",
            order_id="OD002", intent="logistics", resolved=True,
            slot_sources={"order_id": "user_correction"},
        )
        wm_corr = manager.get_working_memory("sess-corr-001", "user-D")
        results.append({
            "case_id": "correction_1",
            "category": "correction",
            "description": "用户纠正订单号后使用新值",
            "passed": wm_corr["order_id"] == "OD002",
            "expected": "OD002",
            "actual": wm_corr["order_id"],
        })

        # === 5. Long-term Preference ===
        manager.process_user_message(
            "以后请用简洁回答",
            user_id="user-E", session_id="sess-pref-A",
        )
        # 新 session 检索
        context_e = manager.retrieve_context(user_id="user-E", session_id="sess-pref-B")
        has_pref = "user_profile" in context_e and "preferred_response_style" in context_e["user_profile"]
        results.append({
            "case_id": "long_term_preference_1",
            "category": "long_term_preference",
            "description": "偏好跨 session 生效",
            "passed": has_pref,
            "expected": True,
            "actual": has_pref,
        })

        # === 6. Conflict Resolution ===
        manager.process_user_message("以后请用详细回答", user_id="user-F", session_id="sess-conf-A")
        manager.process_user_message("以后请用简洁回答", user_id="user-F", session_id="sess-conf-A")
        profile_f = mem_store.get_active(user_id="user-F", memory_type="profile")
        results.append({
            "case_id": "conflict_resolution_1",
            "category": "conflict_resolution",
            "description": "用户纠正偏好后使用新值",
            "passed": len(profile_f) == 1 and profile_f[0].value == "简洁",
            "expected": "简洁",
            "actual": profile_f[0].value if profile_f else None,
        })

        # === 7. Memory Pollution ===
        noise_messages = ["今天天气不错", "好的", "哈哈", "嗯", "ok"]
        for msg in noise_messages:
            manager.process_user_message(msg, user_id="user-G", session_id="sess-poll-A")
        profile_g = mem_store.get_active(user_id="user-G", memory_type="profile")
        results.append({
            "case_id": "memory_pollution_1",
            "category": "memory_pollution",
            "description": "无价值闲聊不写入长期 Memory",
            "passed": len(profile_g) == 0,
            "expected": 0,
            "actual": len(profile_g),
        })

        # === 8. Token / Context Cost ===
        # 对比 full_history vs sliding_window vs summary vs hybrid
        for i in range(20):
            manager.record_conversation_message(
                user_id="user-H", session_id="sess-cost-A",
                role="user" if i % 2 == 0 else "assistant",
                content=f"消息内容 {i} " + "x" * 50,
            )

        full_history = mem_store.get_conversation_window(
            session_id="sess-cost-A", user_id="user-H", window_size=1000,
        )
        window_10 = mem_store.get_conversation_window(
            session_id="sess-cost-A", user_id="user-H", window_size=10,
        )

        full_tokens = sum(len(m["content"]) for m in full_history)
        window_tokens = sum(len(m["content"]) for m in window_10)

        results.append({
            "case_id": "token_cost_1",
            "category": "token_cost",
            "description": "window 模式比 full_history 节省 token",
            "passed": window_tokens < full_tokens,
            "expected": f"window<{full_tokens}",
            "actual": f"window={window_tokens}, full={full_tokens}",
        })

    # 汇总
    total = len(results)
    passed = sum(1 for r in results if r["passed"])

    # 分类统计
    categories: dict[str, dict] = {}
    for r in results:
        cat = r["category"]
        if cat not in categories:
            categories[cat] = {"total": 0, "passed": 0}
        categories[cat]["total"] += 1
        if r["passed"]:
            categories[cat]["passed"] += 1

    report = {
        "report_version": "memory-eval-v2",
        "total_cases": total,
        "passed_cases": passed,
        "pass_rate": round(passed / total, 4) if total > 0 else 0,
        "categories": {
            cat: {
                "total": v["total"],
                "passed": v["passed"],
                "pass_rate": round(v["passed"] / v["total"], 4),
            }
            for cat, v in categories.items()
        },
        "context_continuity_rate": categories.get("context_continuity", {}).get("passed", 0) / max(categories.get("context_continuity", {}).get("total", 1), 1),
        "cross_user_leakage_rate": 0.0 if all(r["passed"] for r in results if r["category"] == "user_isolation") else 1.0,
        "stale_memory_error_rate": 0.0 if all(r["passed"] for r in results if r["category"] == "stale_memory") else 1.0,
        "correction_accuracy": 1.0 if all(r["passed"] for r in results if r["category"] == "correction") else 0.0,
        "long_term_preference_rate": 1.0 if all(r["passed"] for r in results if r["category"] == "long_term_preference") else 0.0,
        "conflict_resolution_rate": 1.0 if all(r["passed"] for r in results if r["category"] == "conflict_resolution") else 0.0,
        "memory_pollution_rate": 0.0 if all(r["passed"] for r in results if r["category"] == "memory_pollution") else 1.0,
        "token_cost_reduction": {
            "full_history_tokens": full_tokens,
            "window_tokens": window_tokens,
            "reduction_rate": round(1 - window_tokens / full_tokens, 4) if full_tokens > 0 else 0,
        },
        "results": results,
        "failures": [r for r in results if not r["passed"]],
    }
    report["release_gate"] = {
        "thresholds": {
            "pass_rate": 1.0,
            "cross_user_leakage_rate": 0.0,
            "stale_memory_error_rate": 0.0,
            "correction_accuracy": 1.0,
            "memory_pollution_rate": 0.0,
        },
        "passed": passed == total,
    }

    return report


def main() -> None:
    report = run_eval()
    output_path = ROOT / "evals/memory-eval-extended-report.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["release_gate"]["passed"] else 1)


if __name__ == "__main__":
    main()
