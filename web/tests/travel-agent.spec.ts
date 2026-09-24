import { expect, test } from "@playwright/test";

test("creates a session, groups progress, and previews an artifact", async ({ page }) => {
  let sessionHeader = "";
  let chatFinished = false;

  await page.route("http://127.0.0.1:8000/api/events", async (route) => {
    await route.fulfill({
      contentType: "text/event-stream",
      body: [
        'event: progress\ndata: {"entry_id":"n1","level":1,"status":"pending","label":"Planning Tokyo trip","parent_id":null}\n\n',
        'event: progress\ndata: {"entry_id":"n2","level":2,"status":"pending","label":"Checking flights","parent_id":"n1"}\n\n',
        'event: progress\ndata: {"entry_id":"n2","level":2,"status":"resolved","label":"Checking flights","parent_id":"n1"}\n\n',
        'event: progress\ndata: {"entry_id":"n4","level":1,"status":"resolved","label":"Researching stays","parent_id":null}\n\n',
        'event: progress\ndata: {"entry_id":"n5","level":2,"status":"resolved","label":"Comparing hotels","parent_id":"n4"}\n\n',
        'event: progress\ndata: {"entry_id":"n3","level":2,"status":"resolved","label":"Updating trip details","parent_id":null}\n\n',
      ].join(""),
    });
  });
  await page.route("http://127.0.0.1:8000/api/chat", async (route) => {
    sessionHeader = (await route.request().allHeaders())["x-session-id"];
    await new Promise((resolve) => setTimeout(resolve, 300));
    chatFinished = true;
    await route.fulfill({ json: { response: "## Your trip\n\nTokyo is ready." } });
  });
  await page.route("http://127.0.0.1:8000/api/artifacts", async (route) => {
    await route.fulfill({ json: chatFinished ? [{ id: "tokyo.md", name: "tokyo.md" }] : [] });
  });
  await page.route("http://127.0.0.1:8000/api/artifacts/tokyo.md", async (route) => {
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
  await expect(page.getByTestId("children-n4")).toHaveCount(0);
  await expect(page.locator("#trip-progress")).toHaveClass(/max-h-32/);
  await expect(page.locator("#trip-progress")).toHaveJSProperty("scrollTop", await page.locator("#trip-progress").evaluate((element) => element.scrollHeight - element.clientHeight));
  await page.getByRole("button", { name: /Researching stays/ }).click();
  await expect(page.getByTestId("children-n4").getByTestId("progress-n5")).toContainText("Comparing hotels");
  const rootOrder = await page.locator('[data-testid="progress-n1"], [data-testid="progress-n3"], [data-testid="progress-n4"]').evaluateAll((items) => items.map((item) => item.getAttribute("data-testid")));
  expect(rootOrder).toEqual(["progress-n1", "progress-n3", "progress-n4"]);
  await expect(page.getByRole("heading", { name: "Your trip" })).toBeVisible();
  await expect(page.getByTestId("chat-scroll")).toHaveJSProperty("scrollTop", await page.getByTestId("chat-scroll").evaluate((element) => element.scrollHeight - element.clientHeight));
  const layout = await page.evaluate(() => ({ pageHeight: document.documentElement.scrollHeight, viewportHeight: document.documentElement.clientHeight }));
  expect(layout.pageHeight).toBe(layout.viewportHeight);
  const footer = await page.getByTestId("chat-footer").boundingBox();
  expect(Math.round(footer!.y + footer!.height)).toBe(page.viewportSize()!.height);
  await page.getByRole("button", { name: "Trip progress" }).click();
  await expect(page.locator("#trip-progress")).toHaveCount(0);
  await page.getByRole("button", { name: "Trip progress" }).click();
  await expect(page.locator("#trip-progress")).toBeVisible();
  expect(sessionHeader).toMatch(/^[0-9a-f-]{36}$/);

  await page.getByRole("button", { name: "tokyo.md" }).click();
  await expect(page.getByTestId("artifact-preview")).toContainText("Visit Asakusa");
});
