import { defineConfig, devices } from "@playwright/test";

const consoleUrl = process.env.TOOLGATE_CONSOLE_URL ?? "http://localhost:3101";

/**
 * Smoke tests drive the real stack: the console signs in through the gateway's own OAuth flow.
 * Start Postgres and Redis first (`make services migrate seed`); the API and console are started here
 * unless they are already running.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: consoleUrl,
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"],
  },
  webServer: [
    {
      command: "cd ../backend && set -a && . ../.env && set +a && .venv/bin/uvicorn toolgate.main:app --port 8101",
      url: "http://127.0.0.1:8101/healthz",
      reuseExistingServer: true,
      timeout: 60_000,
    },
    {
      command: "pnpm start",
      url: `${consoleUrl}/signed-out`,
      reuseExistingServer: true,
      timeout: 60_000,
    },
  ],
});
