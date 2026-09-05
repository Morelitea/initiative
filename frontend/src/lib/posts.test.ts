/**
 * The post length limit is one number in two places, and the server owns it.
 *
 * The composer needs it locally to show a remaining count while somebody
 * types; the endpoint needs it to refuse what arrives. This pins the copy to
 * the original the way `locale-keys` pins the two message catalogues together,
 * so a change on the backend cannot leave the composer counting down to the
 * wrong number.
 */
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { MAX_POST_TEXT_CHARS } from "@/lib/posts";

const SCHEMA = path.resolve(__dirname, "../../../backend/app/schemas/tenant/post.py");

describe("post length limit", () => {
  it("matches the server's own ceiling", () => {
    const source = fs.readFileSync(SCHEMA, "utf-8");
    const match = source.match(/^MAX_POST_TEXT_CHARS = ([\d_]+)$/m);
    expect(match, "MAX_POST_TEXT_CHARS not found in the backend schema").toBeTruthy();
    expect(Number(match?.[1].replaceAll("_", ""))).toBe(MAX_POST_TEXT_CHARS);
  });
});
