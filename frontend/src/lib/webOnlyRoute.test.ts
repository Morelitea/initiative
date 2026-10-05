/**
 * The website's front pages are not part of the app packages: in an app
 * build each one redirects to sign-in and renders nothing, and the page's own
 * import sits behind the build flag so the bundle leaves it out.
 */
import fs from "node:fs";
import path from "node:path";

import { isRedirect } from "@tanstack/react-router";
import { describe, expect, it } from "vitest";

import { NotInApp, signInInApp } from "./webOnlyRoute";

const ROUTES_DIR = path.resolve(import.meta.dirname, "../routes/_serverRequired");
const FRONT_PAGES = [
  "welcome.tsx",
  "pricing.tsx",
  "download.tsx",
  "whats-new.index.tsx",
  "whats-new.$version.tsx",
];

describe("web-only routes", () => {
  it("sends an app package to sign-in", () => {
    let thrown: unknown;
    try {
      signInInApp(true);
    } catch (error) {
      thrown = error;
    }
    expect(isRedirect(thrown)).toBe(true);
    expect((thrown as { options: { to: string } }).options.to).toBe("/login");
  });

  it("lets the website through", () => {
    expect(() => signInInApp(false)).not.toThrow();
  });

  it("renders nothing in an app package", () => {
    expect(NotInApp()).toBeNull();
  });

  it.each(FRONT_PAGES)("%s redirects in the apps and keeps its page out of them", (file) => {
    const source = fs.readFileSync(path.join(ROUTES_DIR, file), "utf8");

    expect(source).toContain("beforeLoad: leaveForSignIn");
    // The page's import must sit in the web branch, so a Capacitor build drops it.
    expect(source).toMatch(
      /component: __IS_CAPACITOR__\s*\?\s*NotInApp\s*:\s*lazyRouteComponent\(/
    );
  });
});
