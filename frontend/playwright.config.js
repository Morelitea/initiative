import { defineConfig, devices } from "@playwright/test";
// The browser journeys (e2e/*.journey.ts): the image, served as the example
// compose file serves it, driven in Chromium. CI starts the server
// (.github/workflows/journeys.yml); locally, point JOURNEYS_URL at a fresh
// install. Each run needs an empty database: the first journey registers the
// first owner.
export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.journey.ts",
  // One install, built up in order: the journeys share its owner.
  workers: 1,
  fullyParallel: false,
  // A journey that passes on a second try is a flake to fix, not a pass.
  retries: 0,
  timeout: 60000,
  expect: { timeout: 10000 },
  // In CI, a failure is also an annotation on the run.
  reporter: [
    ...(process.env.CI ? [["github"]] : []),
    ["list"],
    ["html", { open: "never", outputFolder: "playwright-report" }],
  ],
  use: {
    baseURL: process.env.JOURNEYS_URL ?? "http://localhost:8173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
