"""Generate a diverse, executable MVP evaluation set."""
import json
from pathlib import Path

cases = []


def add(case_id, category, message, preconditions, intent, tools, fact=None, citation=False,
        handoff=False, status=200, message_contains=None, ticket_category=None,
        rule_version=None, turns=None):
    cases.append({
        "case_id": case_id, "category": category, "input": message,
        "preconditions": preconditions, "expected_intent": intent,
        "allowed_tools": tools, "expected_fact": fact,
        "expected_citation": citation, "expected_handoff": handoff,
        "expected_status": status, "expected_message_contains": message_contains,
        "expected_ticket_category": ticket_category,
        "expected_rule_version": rule_version,
        "turns": turns,
        "version": "v2", "actual_result": None,
    })


user1 = "user-demo-001"
order1 = "OD202608001"

# 正常主流程：20 条，刻意覆盖中文口语、英文和不同表达。
for index, message in enumerate((
    "订单到哪里了？", "物流到哪一步了", "帮我查下包裹",
    "预计什么时候到？", "运输进度如何", "我的包裹还在路上吗",
), 1):
    add(f"normal-logistics-{index:02d}", "normal", message, {"user_id": user1, "order_id": order1},
        "logistics", ["query_order_logistics"], "运输中")
for index, message in enumerate((
    "我想退货", "这个可以退吗", "尺码不合适，想退", "能不能换货？",
), 1):
    add(f"normal-return-{index:02d}", "normal", message,
        {"user_id": user1, "order_id": order1, "return_reason": "尺码不合适"},
        "return", ["check_return_eligibility"], "eligible")
for index, message in enumerate((
    "海外仓发货多久能到？", "海外仓物流时效", "海外仓一般几天送到",
    "发货后预计多久到货", "配送时间是多少",
), 1):
    add(f"normal-policy-{index:02d}", "normal", message, {}, "policy", ["search_policy"],
        "5-10 个工作日", citation=True, rule_version="shipping-policy-v1")

# 业务边界：10 条。
add("boundary-owner-logistics-01", "boundary", "查一下这个订单物流", {"user_id": "user-demo-002", "order_id": order1},
    "logistics", ["query_order_logistics"], handoff=True, status=403)
add("boundary-owner-return-01", "boundary", "我能退这个吗", {"user_id": "user-demo-002", "order_id": order1, "return_reason": "尺码不合适"},
    "return", ["check_return_eligibility"], handoff=True, status=403)
add("boundary-missing-return-01", "boundary", "我想退货", {"user_id": user1, "order_id": order1},
    "return", ["check_return_eligibility"], handoff=True, status=400)
add("boundary-missing-return-02", "boundary", "退货（原因：）", {"user_id": user1, "order_id": order1},
    "return", ["check_return_eligibility"], handoff=True, status=400, message_contains="退货原因")
add("boundary-missing-identity-01", "boundary", "查询物流状态", {"order_id": order1},
    "logistics", ["query_order_logistics"], handoff=True, status=400)
add("boundary-return-status-01", "boundary", "订单状态异常还能退吗", {"user_id": "user-demo-002", "order_id": "OD202608002", "return_reason": "尺码不合适"},
    "return", ["check_return_eligibility"], handoff=True, status=409)
add("boundary-case-07", "boundary", "退货规则适用于哪个地区", {},
    "policy", ["search_policy"], "14 天", citation=True, rule_version="return-policy-v1")
add("boundary-case-08", "boundary", "我想退货（原因：商品质量问题）", {"user_id": user1, "order_id": order1},
    "return", ["check_return_eligibility"], "human_review", handoff=True)
add("boundary-case-09", "boundary", "订单号是错的 OD202609999", {"user_id": user1, "order_id": "OD202609999"},
    "logistics", ["query_order_logistics"], handoff=True, status=404)
add("boundary-case-10", "boundary", "订单物流查不到", {"order_id": order1},
    "logistics", ["query_order_logistics"], handoff=True, status=400)

# Tool 异常：8 条。
for index, message in enumerate(("订单到哪里了？", "查物流", "包裹进度", "tracking status"), 1):
    add(f"tool-error-order-{index:02d}", "tool_error", message, {"user_id": user1, "order_id": "OD202609999"},
        "logistics", ["query_order_logistics"], handoff=True, status=404)
for index, message in enumerate(("我想退货", "退货怎么处理", "return this order", "我能退吗"), 1):
    add(f"tool-error-return-{index:02d}", "tool_error", message,
        {"user_id": user1, "order_id": "OD202609999", "return_reason": "尺码不合适"},
        "return", ["check_return_eligibility"], handoff=True, status=404)

# 风险与转人工：至少 8 条，并独立验证支付敏感分类。
for index, message in enumerate(("一直不退款，我要投诉", "退款争议投诉", "我要投诉退款进度", "客户一直没收到退款"), 1):
    add(f"risk-complaint-{index:02d}", "risk", message, {"order_id": order1}, "complaint",
        ["create_service_ticket", "handoff_human"], "待人工处理", handoff=True, ticket_category="complaint_or_dispute")
for index, message in enumerate(("帮我修改银行卡收款人", "请更换付款账户", "change my bank account", "支付密码被改了"), 1):
    add(f"risk-payment-{index:02d}", "risk", message, {}, "payment_sensitive",
        ["create_service_ticket"], "待人工处理", handoff=True,
        ticket_category="payment_sensitive", message_contains="人工")
add("risk-quality-01", "risk", "商品质量问题想退货", {"user_id": user1, "order_id": order1, "return_reason": "商品质量问题"},
    "return", ["check_return_eligibility", "handoff_human"], "human_review", handoff=True)
add("risk-low-confidence-01", "risk", "这个问题很复杂，请帮我处理", {}, "unknown", ["handoff_human"],
    "待人工处理", handoff=True)

# 知识无依据/版本冲突：4 条。
add("knowledge-no-basis-01", "knowledge", "帮我修改收货人银行卡", {}, "payment_sensitive",
    ["create_service_ticket"], "待人工处理", handoff=True, ticket_category="payment_sensitive")
add("knowledge-version-conflict-01", "knowledge", "退货规则 return policy", {}, "policy", ["search_policy"],
    "14 天", citation=True, rule_version="return-policy-v1")
add("knowledge-no-basis-03", "knowledge", "平台是否支持任意商品永久退款", {}, "complaint", ["create_service_ticket"],
    "待人工处理", handoff=True, ticket_category="complaint_or_dispute")
add("knowledge-no-basis-04", "knowledge", "海关税费能不能退", {}, "complaint", ["create_service_ticket"],
    "待人工处理", handoff=True, ticket_category="complaint_or_dispute")

# 交互契约与写操作回归：5 条。
add("ux-return-success-message", "normal", "我想退货", {"user_id": user1, "order_id": order1, "return_reason": "尺码不合适"},
    "return", ["check_return_eligibility"], "eligible", message_contains="符合退货条件")
add("ux-policy-no-evidence", "knowledge", "帮我修改银行卡收款人", {}, "payment_sensitive", ["create_service_ticket"],
    "待人工处理", handoff=True, message_contains="人工", ticket_category="payment_sensitive")
add("ux-complaint-ticket-message", "risk", "一直不退款，我要投诉", {"order_id": order1}, "complaint",
    ["create_service_ticket"], "待人工处理", handoff=True, message_contains="工单", ticket_category="complaint_or_dispute")
add("ux-return-application-next-step", "normal", "确认提交退货申请", {"user_id": user1, "order_id": order1, "return_reason": "尺码不合适"},
    "return_application", ["submit_return_application"], "待审核", message_contains="退货申请")
add("ux-follow-up-logistics", "normal", "那预计什么时候到？", {"user_id": user1, "order_id": order1},
    "logistics", ["query_order_logistics"], "运输中")

# 多轮会话：验证上下文继承、参数补充和连续未解决转人工。
add("conversation-logistics-follow-up", "normal", "那预计什么时候到？", {"user_id": user1}, "logistics",
    ["query_order_logistics"], "运输中", turns=[
        {"message": "订单到哪里了？", "order_id": order1},
        {"message": "那预计什么时候到？"},
    ])
add("conversation-return-follow-up", "normal", "尺码不合适", {"user_id": user1}, "return",
    ["check_return_eligibility"], "eligible", turns=[
        {"message": "我想退货", "order_id": order1},
        {"message": "尺码不合适"},
    ])
add("conversation-unresolved-handoff", "risk", "还是想退", {"user_id": user1}, "return",
    ["handoff_human"], "连续两次", handoff=True, turns=[
        {"message": "我想退货", "order_id": order1},
        {"message": "还是想退"},
    ])

assert len(cases) == 55
assert {case["category"] for case in cases} == {"normal", "boundary", "tool_error", "risk", "knowledge"}
Path(__file__).with_name("mvp-50.jsonl").write_text(
    "\n".join(json.dumps(row, ensure_ascii=False) for row in cases) + "\n", encoding="utf-8"
)
print(f"generated {len(cases)} executable cases")
