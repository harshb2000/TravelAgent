import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  use: { baseURL: "http://127.0.0.1:3000", trace: "on-first-retry" },
  webServer: [
    { command: "cd .. && TRAVELAGENT_FAKE=1 .venv/bin/python -m uvicorn api.app:app --port 8001", url: "http://127.0.0.1:8001/docs", reuseExistingServer: true },
    { command: "NEXT_PUBLIC_API_URL=http://127.0.0.1:8001 npm run dev", url: "http://127.0.0.1:3000", reuseExistingServer: true },
  ],
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
