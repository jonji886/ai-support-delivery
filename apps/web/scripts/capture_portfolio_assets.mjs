import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";

const baseURL = process.env.BASE_URL || "http://127.0.0.1:5173";
const userId = process.env.DEMO_USER_ID || "user-demo-001";
const orderId = process.env.DEMO_ORDER_ID || "OD202608001";
const assetsDir = resolve(process.cwd(), "../../docs/assets");

await mkdir(assetsDir, { recursive: true });

const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined,
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 960 },
  deviceScaleFactor: 1,
});
const page = await context.newPage();

async function openChat() {
  await page.goto(baseURL);
  await page.getByRole("heading", { name: "使用指引" }).waitFor({ state: "visible", timeout: 15000 });
  await page.locator(".sidebar-bottom .form-input").fill(userId);
  await page.locator(".sidebar-item", { hasText: "Agent Chat" }).first().click();
  await page.getByPlaceholder("输入消息...").waitFor({ state: "visible", timeout: 15000 });
}

async function send(message) {
  const input = page.getByPlaceholder("输入消息...");
  await input.fill(message);
  await input.press("Enter");
  await page.getByText("思考中...").waitFor({ state: "hidden", timeout: 120000 }).catch(() => {});
}

async function capture(name) {
  await page.screenshot({ path: resolve(assetsDir, name), fullPage: true });
  console.log(`captured ${name}`);
}

try {
  await openChat();
  await send(`我的订单 ${orderId} 到哪了？`);
  await page.locator(".message.ai").last().locator(".tool-result").waitFor({ state: "visible", timeout: 120000 });
  await capture("demo-chat.png");

  await openChat();
  await send(`帮我申请退货，订单 ${orderId}，原因：尺码不合适`);
  await page.locator(".confirm-dialog").waitFor({ state: "visible", timeout: 120000 });
  await capture("demo-hitl.png");

  await openChat();
  await send("我要投诉快递员态度恶劣，要求处理");
  await page.locator(".handoff-banner").waitFor({ state: "visible", timeout: 120000 });
  await capture("demo-handoff.png");

  await page.locator(".sidebar-item", { hasText: "可观测性" }).first().click();
  await page.getByRole("heading", { name: "可观测性" }).waitFor({ state: "visible", timeout: 15000 });
  await page.locator(".metric-card").first().waitFor({ state: "visible", timeout: 15000 });
  await capture("demo-observability.png");
} finally {
  await browser.close();
}
