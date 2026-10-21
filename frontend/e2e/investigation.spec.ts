import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";

test("analyst investigates a real queued simulation and explores its evidence", async ({
  page,
}) => {
  const env = readFileSync("../.env", "utf8");
  const password = env.match(/^ADMIN_PASSWORD=(.+)$/m)?.[1];
  if (!password) throw new Error("Run bootstrap before browser tests");
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Your security, in focus." }),
  ).toBeVisible();
  await expect(page.locator(".stat").nth(1).locator("strong")).toBeVisible();
  const previousEvents = Number(
    (
      await page.locator(".stat").nth(1).locator("strong").innerText()
    ).replaceAll(",", ""),
  );
  await page
    .getByRole("button", { name: "Run simulation", exact: true })
    .last()
    .click();
  await expect(
    page.getByText("33 synthetic events queued.", { exact: false }),
  ).toBeVisible();
  const incident = page
    .getByRole("button", { name: "Potential account compromise", exact: true })
    .first();
  await expect(incident).toBeVisible({ timeout: 30000 });
  await expect(page.locator(".stat").nth(1).locator("strong")).toHaveText(
    (previousEvents + 33).toLocaleString(),
    { timeout: 30000 },
  );
  await page.screenshot({
    path: "../docs/screenshots/dashboard.png",
    fullPage: true,
  });
  await incident.click();
  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByRole("heading", { name: "Potential account compromise" }),
  ).toBeVisible();
  await expect(dialog.locator(".detail-meta")).toContainText("events");
  await dialog
    .getByLabel("Status", { exact: true })
    .selectOption("INVESTIGATING");
  await expect(dialog.getByLabel("Status", { exact: true })).toHaveValue(
    "INVESTIGATING",
  );
  await dialog.getByRole("button", { name: "Assign to me" }).click();
  await dialog
    .getByLabel("Analyst note", { exact: true })
    .fill(
      "Browser verification: correlated authentication and admin-access evidence reviewed.",
    );
  await dialog.getByRole("button", { name: "Add note" }).click();
  await expect(
    dialog
      .getByText(
        "Browser verification: correlated authentication and admin-access evidence reviewed.",
      )
      .last(),
  ).toBeVisible();
  await dialog.evaluate((element) => {
    element.scrollTop = 0;
  });
  await page.screenshot({
    path: "../docs/screenshots/incident.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Close incident" }).click();
  await page
    .getByRole("button", { name: "Event explorer", exact: true })
    .click();
  await page.getByLabel("Search events").fill("authentication_success");
  await expect(page.locator(".event-list details").first()).toContainText(
    "authentication success",
  );
  await page.locator(".event-list summary").first().click();
  await expect(page.locator(".event-list details[open] pre")).toContainText(
    "raw_event",
  );
  await page
    .getByRole("button", { name: "Detection rules", exact: true })
    .click();
  await expect(page.locator("tbody tr")).toHaveCount(19);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Overview", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Your security, in focus." }),
  ).toBeVisible();
  await page.screenshot({
    path: "../docs/screenshots/mobile.png",
    fullPage: true,
  });
  expect(errors).toEqual([]);
});
