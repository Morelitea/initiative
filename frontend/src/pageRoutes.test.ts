import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const ROUTE_TREE = path.resolve(__dirname, "routeTree.gen.ts");
const PAGE_ROUTES = path.resolve(__dirname, "../../backend/app/core/page_routes.json");

/** Every full path the router knows, read from the generated route tree. */
const routerFullPaths = (): string[] => {
  const source = fs.readFileSync(ROUTE_TREE, "utf8");
  const union = source.match(/\n {2}fullPaths:\n((?: {4}\| '[^']*'\n)+)/);
  if (!union) throw new Error("fullPaths union not found in routeTree.gen.ts");
  return [...new Set([...union[1].matchAll(/\| '([^']*)'/g)].map((m) => m[1]))].sort();
};

describe("the page view route list", () => {
  it("is the router's own list of route templates", () => {
    // The server counts a page view under its template only when the template
    // is in backend/app/core/page_routes.json, and as "other" otherwise. Copy
    // the expected list below into that file when the routes change.
    const listed = JSON.parse(fs.readFileSync(PAGE_ROUTES, "utf8")) as string[];

    expect(listed).toEqual(routerFullPaths());
  });
});
