import { defineConfig, devices } from "@playwright/test";

const BASE_URL = process.env.BASE_URL || "http://127.0.0.1:5173";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    // 使用系统 Chrome（macOS 13 无法下载 Playwright 自带 chromium；CI 中同样可用 channel）
    channel: "chrome",
  },
  projects: [{ name: "chrome", use: { ...devices["Desktop Chrome"] } }],
});
