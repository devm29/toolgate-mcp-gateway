import { expect, test, type Page } from "@playwright/test";

const USERNAME = process.env.TOOLGATE_E2E_USER ?? "alice";
const PASSWORD = process.env.TOOLGATE_E2E_PASSWORD ?? "toolgate-demo";

async function signIn(page: Page) {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Sign in to Toolgate" })).toBeVisible();
  await page.getByLabel("Username").fill(USERNAME);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("heading", { name: "Allow Toolgate Console?" })).toBeVisible();
  await page.getByRole("button", { name: "Allow", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
}

test("unauthenticated API calls are refused", async ({ request }) => {
  const response = await request.get("/api/gateway/v1/upstreams");
  expect(response.status()).toBe(401);
  const forged = await request.post("/api/gateway/v1/upstreams", {
    headers: { origin: "http://evil.example" },
    data: { name: "pwn", display_name: "x", transport: "stdio", command: "/bin/sh" },
  });
  expect(forged.status()).toBe(403);
});

test("rebound Host headers are refused", async ({ request }) => {
  const response = await request.get("/api/gateway/v1/upstreams", { headers: { host: "attacker.example:3101" } });
  expect(response.status()).toBe(403);
});

test("an admin signs in with OAuth and every console page renders", async ({ page }) => {
  await signIn(page);
  await expect(page.getByText(`user:${USERNAME}`)).toBeVisible();

  await page.getByRole("link", { name: "Servers" }).first().click();
  await expect(page.getByRole("heading", { name: "Upstream servers" })).toBeVisible();

  await page.getByRole("link", { name: "Tools" }).first().click();
  await expect(page.getByRole("heading", { name: "Tool inventory" })).toBeVisible();
  const firstTool = page.locator("tbody tr").first();
  await expect(firstTool).toBeVisible();
  await firstTool.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("Upstream now").first()).toBeVisible();
  // A same-origin write goes through the relay with the admin's own token.
  await dialog.getByRole("button", { name: "Re-scan" }).click();
  await expect(page.getByText("Re-scanned")).toBeVisible();
  await page.keyboard.press("Escape");

  await page.getByRole("link", { name: "Approvals" }).first().click();
  await expect(page.getByRole("heading", { name: "Approval queue" })).toBeVisible();

  await page.getByRole("link", { name: "Policies" }).first().click();
  await expect(page.getByRole("heading", { name: "Policies" })).toBeVisible();

  await page.getByRole("link", { name: "Activity" }).first().click();
  await expect(page.getByRole("heading", { name: "Activity" })).toBeVisible();
  await page.getByRole("tab", { name: "History" }).click();
  await expect(page.getByLabel("Filter by decision")).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "You're signed out" })).toBeVisible();
  const after = await page.request.get("/api/gateway/v1/upstreams");
  expect(after.status()).toBe(401);
});
