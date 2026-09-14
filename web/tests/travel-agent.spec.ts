import { expect, test } from "@playwright/test";

test("creates a session, groups progress, and previews an artifact", async ({ page }) => {
  let sessionHeader = "";
  let chatFinished = false;

  await page.route("http://127.0.0.1:8001/api/events", async (route) => {
    await route.fulfill({
      contentType: "text/event-stream",
      body: [
        'event: progress\ndata: {"entry_id":"n1","level":1,"status":"pending","label":"Planning Tokyo trip","parent_id":null}\n\n',
        'event: progress\ndata: {"entry_id":"n2","level":2,"status":"pending","label":"Checking flights","parent_id":"n1"}\n\n',
        'event: progress\ndata: {"entry_id":"n2","level":2,"status":"resolved","label":"Checking flights","parent_id":"n1"}\n\n',
        'event: progress\ndata: {"entry_id":"n3","level":1,"status":"resolved","label":"Researching stays","parent_id":null}\n\n',
        'event: progress\ndata: {"entry_id":"n4","level":2,"status":"resolved","label":"Comparing hotels","parent_id":"n3"}\n\n',
      ].join(""),
    });
  });
  await page.route("http://127.0.0.1:8001/api/chat", async (route) => {
    sessionHeader = (await route.request().allHeaders())["x-session-id"];
    await new Promise((resolve) => setTimeout(resolve, 300));
    chatFinished = true;
    await route.fulfill({ json: { response: "## Your trip\n\nTokyo is ready." } });
  });
  await page.route("http://127.0.0.1:8001/api/artifacts", async (route) => {
    await route.fulfill({ json: chatFinished ? [{ id: "tokyo.md", name: "tokyo.md" }] : [] });
  });
  await page.route("http://127.0.0.1:8001/api/artifacts/tokyo.md", async (route) => {
    await route.fulfill({ json: { id: "tokyo.md", name: "tokyo.md", content: "# Tokyo itinerary\n\nVisit Asakusa." } });
  });

  await page.goto("/");
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.getByRole("button", { name: "Switch to light mode" }).click();
  await expect(page.locator("html")).not.toHaveClass(/dark/);
  await page.getByRole("button", { name: "Switch to dark mode" }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.getByRole("textbox", { name: "Message", exact: true }).fill("Plan Tokyo");
  await page.getByLabel("Send message").click();

  await expect(page.getByTestId("progress-n1")).toContainText("Planning Tokyo trip");
  await expect(page.getByTestId("progress-n1")).toContainText("Pending");
  await expect(page.getByTestId("children-n1").getByTestId("progress-n2")).toContainText("Complete");
  await expect(page.getByTestId("progress-n2")).toHaveCount(1);
  await expect(page.getByTestId("children-n3")).toHaveCount(0);
  await page.getByRole("button", { name: /Researching stays/ }).click();
  await expect(page.getByTestId("children-n3").getByTestId("progress-n4")).toContainText("Comparing hotels");
  await expect(page.getByRole("heading", { name: "Your trip" })).toBeVisible();
  await expect(page.locator("#trip-progress")).toHaveClass(/max-h-56/);
  await page.getByRole("button", { name: "Trip progress" }).click();
  await expect(page.locator("#trip-progress")).toHaveCount(0);
  await page.getByRole("button", { name: "Trip progress" }).click();
  await expect(page.locator("#trip-progress")).toBeVisible();
  expect(sessionHeader).toMatch(/^[0-9a-f-]{36}$/);

  await page.getByRole("button", { name: "tokyo.md" }).click();
  await expect(page.getByTestId("artifact-preview")).toContainText("Visit Asakusa");
});
