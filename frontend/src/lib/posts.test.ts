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

import {
  hasBody,
  MAX_POLL_OPTION_CHARS,
  MAX_POLL_OPTIONS,
  MAX_POST_TEXT_CHARS,
  MIN_POLL_OPTIONS,
} from "@/lib/posts";

const SCHEMA = path.resolve(__dirname, "../../../backend/app/schemas/tenant/post.py");
const POLL_MODEL = path.resolve(__dirname, "../../../backend/app/models/tenant/post_poll.py");

const serverConstant = (source: string, name: string) => {
  const match = source.match(new RegExp(`^${name} = ([\\d_]+)$`, "m"));
  expect(match, `${name} not found in the backend`).toBeTruthy();
  return Number(match?.[1].replaceAll("_", ""));
};

describe("post length limit", () => {
  it("matches the server's own ceiling", () => {
    const source = fs.readFileSync(SCHEMA, "utf-8");
    expect(serverConstant(source, "MAX_POST_TEXT_CHARS")).toBe(MAX_POST_TEXT_CHARS);
  });
});

describe("poll limits", () => {
  it("match the server's own bounds", () => {
    const source = fs.readFileSync(POLL_MODEL, "utf-8");
    expect(serverConstant(source, "MIN_POLL_OPTIONS")).toBe(MIN_POLL_OPTIONS);
    expect(serverConstant(source, "MAX_POLL_OPTIONS")).toBe(MAX_POLL_OPTIONS);
    expect(serverConstant(source, "MAX_POLL_OPTION_CHARS")).toBe(MAX_POLL_OPTION_CHARS);
  });
});

describe("hasBody", () => {
  // Lexical refuses an editor state whose root has no children, so `{}` — what
  // a headline-only notice stores, and what a notice that is only a headline
  // and a poll stores — is a crash rather than an empty document.
  it("refuses the empty object a bodyless notice stores", () => {
    expect(hasBody({})).toBe(false);
  });

  it("refuses nothing at all", () => {
    expect(hasBody(null)).toBe(false);
    expect(hasBody(undefined)).toBe(false);
  });

  it("accepts a real editor state", () => {
    expect(hasBody({ root: { children: [] } })).toBe(true);
  });
});
