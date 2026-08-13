from pathlib import Path
import re
import subprocess


HTML = Path(__file__).resolve().parents[1] / "apps/web/index.html"


def test_frontend_script_has_valid_javascript_syntax() -> None:
    source = HTML.read_text(encoding="utf-8")
    scripts = re.findall(r"<script>([\s\S]*?)</script>", source)
    assert scripts, "frontend page must contain an inline script"
    result = subprocess.run(
        ["node", "--check", "--input-type=commonjs"],
        input=scripts[-1],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr


def test_dynamic_review_actions_do_not_use_inline_handlers() -> None:
    source = HTML.read_text(encoding="utf-8")
    assert "onclick=\\\"reviewReturn" not in source
    assert "data-application-id" in source
    assert "addEventListener('click'" in source


def test_role_view_whitelist_is_declared() -> None:
    source = HTML.read_text(encoding="utf-8")
    assert "consumer:['guide','chat']" in source
    assert "agent:['chat','tickets']" in source
    assert "supervisor:['tickets','metrics','rules']" in source
    assert "implementer:['guide','metrics','rules']" in source


def test_implementer_is_hidden_from普通_user_role_selector() -> None:
    source = HTML.read_text(encoding="utf-8")
    selector = source.split('<select id="role"', 1)[1].split('</select>', 1)[0]
    assert 'value="implementer"' not in selector
    assert "implementer:'实施管理员'" in source


def test_agent_cannot_see_demo_flow_action() -> None:
    source = HTML.read_text(encoding="utf-8")
    assert "button.textContent.includes('查看演示流程')" in source
    assert "button.dataset.roles='supervisor,implementer'" in source


def test_ticket_processing_uses_in_page_workspace() -> None:
    source = HTML.read_text(encoding="utf-8")
    assert "ticket-detail" in source
    assert "agent-reply" in source
    assert "ticket-submit" in source
    assert "prompt('请输入客服处理回复：')" not in source


def test_ticket_summary_formats_structured_values_and_uses_full_width_detail_layout() -> None:
    source = HTML.read_text(encoding="utf-8")
    assert "function displayText(value)" in source
    assert "displayText(t.summary||t.handoff_reason" in source
    assert 'class="ticket-info"' in source
    assert "grid-column:1 / -1" in source


def test_rightbar_navigation_gives_feedback_when_target_view_is_already_active() -> None:
    source = HTML.read_text(encoding="utf-8")
    assert "function goToView(id,button,source,defaultLabel)" in source
    assert "source.textContent='当前页面'" in source
    assert "goToView('rules'" in source


def test_consumer_chat_has_quick_question_fillers() -> None:
    source = HTML.read_text(encoding="utf-8")
    assert "function fillQuestion(question)" in source
    assert "function initQuickQuestions()" in source
    assert "订单到哪里了？" in source
    assert "我想退货（原因：尺码不合适）" in source
    assert "退款什么时候到账？" in source
    assert "我想投诉并转人工客服" in source


def test_empty_chat_prompt_does_not_reference_missing_right_side_scenarios() -> None:
    source = HTML.read_text(encoding="utf-8")

    assert "从右侧选择一个场景" not in source
    assert "点击下方常见问题开始咨询" in source


def test_consumer_chat_uses_bound_demo_order_without_requiring_reentry() -> None:
    source = HTML.read_text(encoding="utf-8")
    assert "const defaultOrder='OD202608001'" in source
    assert "let currentScenario={order:defaultOrder}" in source
    assert "policy:{message:'海外仓发货多久能到？',order:'OD202608001'" in source


def test_agent_chat_is_read_only_and_replies_from_ticket_workspace() -> None:
    source = HTML.read_text(encoding="utf-8")
    assert "agent-readonly" in source
    assert "客服只读视图" in source
    assert ".agent-readonly .composer" in source
    assert "请从“人工接管”进入工单详情并发送客服回复" in source
