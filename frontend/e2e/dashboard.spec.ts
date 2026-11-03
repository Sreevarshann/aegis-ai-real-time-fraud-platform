import { expect, test } from "@playwright/test";
import { login } from "./helpers";

test.describe("AEGIS dashboard against the running stack", () => {
  test("rejects bad credentials", async ({ page }) => {
    await page.goto("/");
    await page.getByLabel("Password").fill("definitely-wrong");
    await page.getByRole("button", { name: /sign in/i }).click();
    await expect(page.getByRole("alert")).toContainText("Invalid email or password");
  });

  test("overview shows live statistics from the pipeline", async ({ page }) => {
    await login(page);
    await expect(page.getByText("Total transactions")).toBeVisible();
    const total = page.locator("text=Total transactions").locator("xpath=../..").locator(".num").first();
    await expect(total).not.toHaveText("0");
    await expect(page.getByText("All systems operational")).toBeVisible();
  });

  test("simulator button publishes events that flow into the live feed", async ({ page }) => {
    await login(page);
    await page.getByRole("button", { name: "Generate 500 transactions" }).click();
    await expect(page.getByTestId("sim-result")).toContainText("Published");
    await page.getByRole("link", { name: "Live Transactions" }).click();
    await expect(page.getByTestId("feed-mode")).toContainText(/Live stream|Polling/);
    const rows = page.getByTestId("txn-table").locator("tbody tr");
    await expect(rows.first()).toBeVisible();
    expect(await rows.count()).toBeGreaterThan(10);
    await rows.first().click();
    await expect(page.getByRole("dialog", { name: "Transaction details" })).toContainText("Main contributing factors");
  });

  test("an analyst can investigate an alert and record a review", async ({ page }) => {
    await login(page, "analyst@northwind.demo");
    await page.getByRole("link", { name: "Fraud Investigations" }).click();
    const queue = page.getByTestId("alert-queue");
    await expect(queue).toBeVisible();
    const investigate = queue.getByRole("button", { name: "Investigate" }).first();
    if (await investigate.count()) await investigate.click();
    else await queue.getByRole("link", { name: /Open/ }).first().click();
    await expect(page).toHaveURL(/\/investigations\/[0-9a-f-]{36}/);
    await expect(page.getByTestId("engine-badge")).toContainText(/Deterministic engine|Local LLM/);
    await expect(page.getByTestId("narrative")).toContainText("[E1]");
    await expect(page.getByText("Evidence", { exact: true })).toBeVisible();
    await page.getByLabel("Status").selectOption("escalated");
    await page.getByLabel("Analyst notes").fill("Escalated by Playwright E2E test");
    await page.getByRole("button", { name: "Save review" }).click();
    await expect(page.getByText("Saved · alert status synchronised.")).toBeVisible();
  });

  test("data, model and operations pages render real results", async ({ page }) => {
    await login(page);
    await page.getByRole("link", { name: "Data Intelligence" }).click();
    await expect(page.getByTestId("dq-table")).toBeVisible();
    await expect(page.getByTestId("dead-letter-table")).toBeVisible();
    await page.getByRole("link", { name: "Model Intelligence" }).click();
    await expect(page.getByText("PR-AUC").first()).toBeVisible();
    await expect(page.getByText("Confusion matrix")).toBeVisible();
    await page.getByRole("link", { name: "System Operations" }).click();
    await expect(page.getByTestId("service-health")).toContainText("redpanda");
  });

  test("a viewer is read-only", async ({ page }) => {
    await login(page, "viewer@northwind.demo");
    await expect(page.getByRole("button", { name: "Generate 500 transactions" })).toBeDisabled();
    await page.getByRole("link", { name: "Fraud Investigations" }).click();
    await expect(page.getByRole("button", { name: "Investigate" })).toHaveCount(0);
  });

  test("tenants only see their own data", async ({ page }) => {
    await login(page, "analyst@meridian.demo");
    await expect(page.getByText("Meridian Credit Union · synthetic tenant")).toBeVisible();
    await page.getByRole("link", { name: "Live Transactions" }).click();
    const cells = page.getByTestId("txn-table").locator("tbody tr td:nth-child(2)");
    await expect(cells.first()).toBeVisible();
    const customers = await cells.allInnerTexts();
    expect(customers.length).toBeGreaterThan(0);
    for (const c of customers) expect(c).toMatch(/^MR-C/);
  });
});
