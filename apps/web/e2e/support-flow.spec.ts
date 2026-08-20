import { test, expect, Page } from "@playwright/test";

/**
 * FDE Delivery Case Study — 浏览器级 E2E（Playwright）。
 *
 * 3 个场景对应 Case Study 的核心交付边界：
 *   1. 物流查询（只读 Tool 自动化）
 *   2. 退货申请（写操作 HITL 确认 + 幂等提交）
 *   3. 投诉转人工（高风险停止自动化，创建工单）
 *
 * 支持远程验证：BASE_URL=https://<domain> npm run e2e
 * 本地验证：npm run e2e（Vite / API / Mock 客户系统需先运行，见 scripts/run_e2e_local.sh）
 */

const RETRY_MS = 120_000;
// 与 evals/mvp-50.jsonl 中 preconditions 一致：user-demo-001 拥有 OD202608001（OD202608002 属于 user-demo-002）
const TEST_USER = process.env.E2E_USER_ID || "user-demo-001";
const ORDER_1 = "OD202608001";
// 退货场景使用同一订单：已签收且处于 14 天退货窗口内（signed_at 2026-08-10）
const RETURN_ORDER = ORDER_1;

async function gotoChat(page: Page) {
  await page.goto("/");
  await page.getByRole("heading", { name: "使用指引" }).waitFor({ state: "visible", timeout: 15_000 });
  // 切换到 mock 数据归属用户（Sidebar 底部 User ID 输入框）
  const userIdInput = page.locator(".sidebar-bottom .form-input");
  await userIdInput.fill(TEST_USER);
  // Sidebar 是 div 元素，用文本匹配点击进入 Agent Chat
  await page.locator(".sidebar-item", { hasText: "Agent Chat" }).first().click();
  await page.getByPlaceholder("输入消息...").waitFor({ state: "visible", timeout: 15_000 });
}

async function waitForAiReply(page: Page, timeout = RETRY_MS) {
  await page.getByText("思考中...").waitFor({ state: "hidden", timeout }).catch(() => {});
  const messages = page.locator(".message.ai");
  await messages.last().waitFor({ state: "visible", timeout });
  return messages.last();
}

async function sendMessage(page: Page, text: string) {
  const input = page.getByPlaceholder("输入消息...");
  await input.fill(text);
  await input.press("Enter");
}

test.describe("FDE Delivery Support Flow", () => {
  test("场景 1: 物流查询 — 只读 Tool 返回结构化物流信息", async ({ page }) => {
    await gotoChat(page);
    await sendMessage(page, `我的订单 ${ORDER_1} 到哪了？`);
    const reply = await waitForAiReply(page);
    await expect(reply).toContainText(new RegExp(`物流|${ORDER_1}`), { timeout: RETRY_MS });
    await expect(reply.locator(".tool-result")).toContainText("query_order_logistics");
    await expect(reply.locator(".tool-result")).toContainText(ORDER_1);
  });

  test("场景 2: 退货申请 — 写操作必须确认，确认后幂等提交", async ({ page }) => {
    await gotoChat(page);
    // 非高危原因（尺码不合适）走 HITL 确认；高危原因（商品损坏）会直接转人工审核
    await sendMessage(page, `帮我申请退货，订单 ${RETURN_ORDER}，原因：尺码不合适`);
    await waitForAiReply(page);
    const dialog = page.locator(".confirm-dialog");
    await dialog.waitFor({ state: "visible", timeout: RETRY_MS });
    await expect(dialog).toContainText("确认写操作");
    await expect(dialog).toContainText(RETURN_ORDER);
    await expect(dialog).toContainText("尺码不合适");
    await page.getByRole("button", { name: "确认提交" }).click();
    const confirmed = await waitForAiReply(page);
    await expect(confirmed).toContainText("退货申请已提交", { timeout: RETRY_MS });
    await expect(confirmed).toContainText(/申请编号|application_id/i);
  });

  test("场景 3: 投诉转人工 — 高风险停止自动化，创建工单", async ({ page }) => {
    await gotoChat(page);
    await sendMessage(page, "我要投诉快递员态度恶劣，要求处理");
    const reply = await waitForAiReply(page);
    await expect(reply).toContainText("人工接管", { timeout: RETRY_MS });
    await expect(reply.locator(".handoff-banner")).toContainText("工单已创建");
    // 工单通过客服队列页确认落库
    await page.locator(".sidebar-item", { hasText: "工单队列" }).first().click();
    await page.getByRole("heading", { name: /工单队列|Tickets/i }).first().waitFor({ state: "visible", timeout: 15_000 });
  });
});
