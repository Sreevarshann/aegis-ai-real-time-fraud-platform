// Captures genuine screenshots of the running application for the README (make screenshots).
import { expect, test } from "@playwright/test";
import { login } from "./helpers";

const OUT = "../docs/screenshots";
test.skip(!process.env.SCREENSHOTS, "set SCREENSHOTS=1 to capture documentation screenshots");
test.use({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 1 });

test("capture dashboard screenshots", async ({ page }) => {
  test.setTimeout(180_000);
  await login(page, "admin@northwind.demo");
  await page.waitForTimeout(2500);
  await page.screenshot({ path: `${OUT}/01-overview.png`, fullPage: true });

  await page.getByRole("link", { name: "Live Transactions" }).click();
  await expect(page.getByTestId("feed-mode")).toContainText("Live stream");
  await page.waitForTimeout(4000);
  await page.screenshot({ path: `${OUT}/02-live-transactions.png` });
  await page.getByTestId("txn-table").locator("tbody tr").first().click();
  await expect(page.getByRole("dialog")).toContainText("Main contributing factors");
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/03-transaction-detail.png` });
  await page.keyboard.press("Escape");
  await page.goto("/investigations");
  await expect(page.getByTestId("alert-queue")).toBeVisible();
  await page.waitForTimeout(1000);
  await page.screenshot({ path: `${OUT}/04-investigation-queue.png` });

  const btn = page.getByTestId("alert-queue").getByRole("button", { name: "Investigate" }).first();
  await btn.click();
  await expect(page.getByTestId("narrative")).toBeVisible();
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/05-investigation-report.png`, fullPage: true });

  for (const [path, name, file] of [
    ["/data", "dq-table", "06-data-intelligence.png"],
    ["/models", "", "07-model-intelligence.png"],
    ["/operations", "service-health", "08-system-operations.png"],
  ] as const) {
    await page.goto(path);
    if (name) await expect(page.getByTestId(name)).toBeVisible();
    await page.waitForTimeout(2500);
    await page.screenshot({ path: `${OUT}/${file}`, fullPage: true });
  }
});

test("capture an LLM-generated investigation (when one exists)", async ({ page }) => {
  const id = process.env.LLM_INVESTIGATION_ID;
  test.skip(!id, "set LLM_INVESTIGATION_ID to the id of an investigation produced by the Ollama engine");
  await login(page, "analyst@northwind.demo");
  await page.goto(`/investigations/${id}`);
  await expect(page.getByTestId("engine-badge")).toContainText("Local LLM");
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/09-llm-investigation.png` });
});
