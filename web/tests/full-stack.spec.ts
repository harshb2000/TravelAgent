import { expect, test } from "@playwright/test";

test("real API keeps a temporary multi-turn session", async ({ page }) => {
  await page.route("http://127.0.0.1:8000/api/**", (route) => route.continue({ url: route.request().url().replace(":8000", ":8001") }));
  await page.goto("/");
  const message = page.getByRole("textbox", { name: "Message", exact: true });

  await message.fill("Plan Tokyo");
  await page.getByLabel("Send message").click();
  await expect(page.getByText("Planned it.")).toBeVisible();
  await page.getByRole("button", { name: /Planning Tokyo trip/ }).click();
  await expect(page.getByText("Checking flights")).toBeVisible();
  await expect(page.getByRole("button", { name: /tokyo_plan.*_v1\.md/ })).toBeVisible();

  await message.fill("Add Kyoto");
  await page.getByLabel("Send message").click();
  await expect(page.getByText("Message: Add Kyoto")).toBeVisible();
  await expect(page.getByRole("button", { name: /tokyo_plan.*_v2\.md/ })).toBeVisible();

  await page.getByRole("button", { name: /tokyo_plan.*_v2\.md/ }).click();
  await expect(page.getByTestId("artifact-preview")).toContainText("You asked: Add Kyoto");
});
