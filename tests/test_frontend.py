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
    assert "supervisor:['metrics','tickets','rules']" in source
    assert "implementer:['guide','metrics','rules']" in source


def test_role_switcher_is_visually_prominent_and_accessible() -> None:
    source = HTML.read_text(encoding="utf-8")
    assert 'title="切换工作视角"' in source
    assert 'class="role-icon"' in source
    assert 'class="role-label">当前体验角色' in source
    assert 'aria-label="当前体验角色"' in source
    assert ".role:hover,.role:focus-within" in source


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


def test_manual_queue_has_server_pagination_and_search_controls() -> None:
    source = HTML.read_text(encoding="utf-8")
    assert "queueKeyword" in source
    assert "queueType" in source
    assert "queueStatus" in source
    assert "queuePrev" in source and "queueNext" in source
    assert "page_size" in source
    assert "loadTickets(){let tickets=[]" in source


def test_homepage_explains_quick_start_and_role_guides() -> None:
    source = HTML.read_text(encoding="utf-8")
    assert "三步快速上手" in source
    assert "选择角色" in source
    assert "完成一个动作" in source
    assert "看懂交付结果" in source
    assert "不用准备数据，按当前角色直接开始。" in source
    assert "function updateOnboarding(role)" in source


def test_homepage_uses_plain_language_for_tool_verification() -> None:
    source = HTML.read_text(encoding="utf-8")
    assert "用 AI 处理售后问题，但每一步都有依据" in source
    assert "系统会先核对订单、物流和规则" in source
    assert "Tool 核验" not in source


def test_homepage_explains_what_why_and_how_before_secondary_scenarios() -> None:
    source = HTML.read_text(encoding="utf-8")
    assert "它是做什么的？" in source
    assert "为什么要用？" in source
    assert "你会看到什么？" in source
    assert 'aria-label="开始体验"' in source
    assert "推荐体验流程" in source


def test_supervisor_dashboard_explains_metrics_and_supports_actionable_visuals() -> None:
    source = HTML.read_text(encoding="utf-8")
    assert "判断系统是否稳定、问题在哪里、下一步做什么" in source
    assert "业务核实成功率" in source
    assert "转人工率" in source
    assert "知识依据覆盖率" in source
    assert "最近质量趋势" in source
    assert "问题类型分布" in source
    assert "风险原因排行" in source
    assert "function renderTrend(trend)" in source
    assert "function renderDistribution(targetId,data,labelMap)" in source
    assert "metrics.handoff_rate" in source
    assert "function formatPercent(value)" in source
    assert "formatPercent(metrics.tool_success_rate)" in source
    assert "formatPercent(metrics.handoff_rate)" in source
    assert "formatPercent(metrics.citation_rate)" in source
    assert "const riskLabels=" in source
    assert "function renderRiskDistribution(data)" in source
    assert "退换货信息不完整" in source
    assert "risk-code" in source
    assert "position:relative;flex:1;height:155px" in source
    assert 'id="metricsSummary"' in source
    assert "function buildMetricsSummary(metrics)" in source
    assert "当前需要重点关注" in source
    assert "data-tip=" in source
    assert 'tabindex="0"' in source
    assert "最近风险事件" not in source
    assert "fetch(API+'/admin/events'" not in source
    assert "renderRiskDistribution(metrics.error_distribution)" in source


def test_homepage_has_single_role_aware_primary_task_and_direct_role_actions() -> None:
    source = HTML.read_text(encoding="utf-8")
    assert 'id="taskAction"' in source
    assert 'id="taskDescription"' in source
    assert "function runPrimaryAction()" in source
    assert "function runRoleAction(role)" in source
    assert "推荐体验流程" in source
    assert "其他场景入口" in source
    assert "function switchRoleAndGo(role,view)" in source
    assert "switchRoleAndGo('agent','tickets')" in source
    assert "switchRoleAndGo('supervisor','metrics')" in source
    assert "function defaultView(){return roleViews[$('role').value]?.[0]||'guide'}" in source


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


def test_review_feedback_uses_toast_and_custom_rejection_modal() -> None:
    source = HTML.read_text(encoding="utf-8")
    assert 'id="toastStack"' in source
    assert 'id="rejectModal"' in source
    assert "function showToast(title,message,type='success')" in source
    assert "function openRejectModal(applicationId)" in source
    assert "function confirmReject()" in source
    assert "showToast(decision==='approved'?'退货申请已审核通过'" in source
    assert "window.alert" not in source
    assert "window.prompt" not in source
