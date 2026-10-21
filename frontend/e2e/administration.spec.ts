import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";

test("administrator manages assets and rules and creates a restricted viewer", async ({
  page,
}) => {
  const password = readFileSync("../.env", "utf8").match(
    /^ADMIN_PASSWORD=(.+)$/m,
  )?.[1];
  if (!password) throw new Error("Missing local credentials");
  await page.goto("/");
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByRole("button", { name: "Assets", exact: true }).click();
  await page.getByLabel("host", { exact: true }).fill("qa-host");
  await page.getByLabel("service", { exact: true }).fill("qa-service");
  await page.getByLabel("owner", { exact: true }).fill("security-team");
  await page
    .getByLabel("Criticality", { exact: false })
    .selectOption("critical");
  await page.getByRole("button", { name: "Save asset", exact: true }).click();
  await expect(page.getByRole("cell", { name: "security-team" })).toBeVisible();
  await page
    .getByRole("button", { name: "Detection rules", exact: true })
    .click();
  const toggle = page.getByRole("button", {
    name: "Toggle AUTH-001",
    exact: true,
  });
  await expect(toggle).toHaveText("Enabled");
  await toggle.click();
  await expect(toggle).toHaveText("Disabled");
  await toggle.click();
  await expect(toggle).toHaveText("Enabled");
  await page
    .getByRole("button", { name: "Administration", exact: true })
    .click();
  const username = "viewer-" + Date.now();
  await page.getByLabel("Username", { exact: true }).fill(username);
  await page
    .getByLabel("Initial password", { exact: true })
    .fill("test-viewer-pass-123");
  await page.getByRole("button", { name: "Create user", exact: true }).click();
  await expect(
    page.getByRole("cell", { name: username, exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Audit trail", exact: true }).click();
  await expect(
    page.getByRole("cell", { name: "user_created", exact: true }).first(),
  ).toBeVisible();
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await page.getByLabel("Username", { exact: true }).fill(username);
  await page
    .getByLabel("Password", { exact: true })
    .fill("test-viewer-pass-123");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Your security, in focus." }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Administration", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Run simulation", exact: true }),
  ).toHaveCount(0);
});
