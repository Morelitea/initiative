import { HttpResponse, http } from "msw";

/**
 * What the app says about its own release.
 *
 * The sidebar footer reads both on every render, so every suite that draws the
 * sidebar asks them — including the many that are not about releases at all.
 * Unhandled, each one fails somewhere after the test that started it, which is
 * console output arriving while the worker is closing.
 *
 * `null` is "nothing newer is known": a version here would draw the update
 * affordance into all of those suites.
 */
export const versionHandlers = [
  http.get("/api/v1/version/latest", () => HttpResponse.json({ version: null })),
  http.get("/api/v1/changelog", () => HttpResponse.json({ entries: [] })),
];
