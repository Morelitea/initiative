import { describe, expect, it } from "vitest";

import { sanitizeUrl, validateUrl } from "./url";

/**
 * Editor documents are cross-user stored content, so a link URL persisted by
 * one user is later rendered (and potentially opened) in another user's
 * browser. These cases pin the strict-allowlist contract that neutralizes
 * stored-XSS vectors (javascript:/data:/vbscript:) at every choke point.
 */
describe("sanitizeUrl", () => {
  it("neutralizes javascript: URLs to about:blank", () => {
    expect(sanitizeUrl("javascript:alert(1)")).toBe("about:blank");
    expect(sanitizeUrl("JavaScript:alert(1)")).toBe("about:blank");
    // Leading/trailing whitespace must not smuggle the scheme through.
    expect(sanitizeUrl("  javascript:alert(1)  ")).toBe("about:blank");
    // Tab/newline obfuscation inside the scheme name.
    expect(sanitizeUrl("java\tscript:alert(1)")).toBe("about:blank");
  });

  it("neutralizes other dangerous schemes", () => {
    expect(sanitizeUrl("data:text/html,<script>alert(1)</script>")).toBe("about:blank");
    expect(sanitizeUrl("vbscript:msgbox(1)")).toBe("about:blank");
    expect(sanitizeUrl("file:///etc/passwd")).toBe("about:blank");
    expect(sanitizeUrl("blob:https://evil.test/uuid")).toBe("about:blank");
  });

  it("passes allowlisted absolute URLs through unchanged", () => {
    expect(sanitizeUrl("https://example.com/path?q=1#frag")).toBe(
      "https://example.com/path?q=1#frag"
    );
    expect(sanitizeUrl("http://example.com")).toBe("http://example.com");
    expect(sanitizeUrl("mailto:user@example.com")).toBe("mailto:user@example.com");
    expect(sanitizeUrl("tel:+15555550123")).toBe("tel:+15555550123");
    expect(sanitizeUrl("sms:+15555550123")).toBe("sms:+15555550123");
  });

  it("passes relative references through unchanged", () => {
    expect(sanitizeUrl("/projects/1")).toBe("/projects/1");
    expect(sanitizeUrl("#heading-anchor")).toBe("#heading-anchor");
    expect(sanitizeUrl("./relative")).toBe("./relative");
    expect(sanitizeUrl("../up")).toBe("../up");
    expect(sanitizeUrl("?query=only")).toBe("?query=only");
  });

  it("leaves bare protocol-less domains for the caller to format", () => {
    expect(sanitizeUrl("example.com/foo")).toBe("example.com/foo");
  });

  it("neutralizes empty input", () => {
    expect(sanitizeUrl("")).toBe("about:blank");
    expect(sanitizeUrl("   ")).toBe("about:blank");
  });
});

describe("validateUrl", () => {
  it("rejects dangerous schemes so they can never be stored", () => {
    expect(validateUrl("javascript:alert(1)")).toBe(false);
    expect(validateUrl("JAVASCRIPT:alert(1)")).toBe(false);
    expect(validateUrl("data:text/html,<script>alert(1)</script>")).toBe(false);
    expect(validateUrl("vbscript:msgbox(1)")).toBe(false);
    // Loose, unanchored matchers historically allowed a javascript: URL when it
    // happened to contain a colon followed by a domain-like substring.
    expect(validateUrl("javascript:alert(document.domain)")).toBe(false);
  });

  it("accepts allowlisted absolute URLs", () => {
    expect(validateUrl("https://example.com")).toBe(true);
    expect(validateUrl("http://example.com/path")).toBe(true);
    expect(validateUrl("mailto:user@example.com")).toBe(true);
    expect(validateUrl("tel:+15555550123")).toBe(true);
  });

  it("accepts the insertion placeholder and heading anchors", () => {
    expect(validateUrl("https://")).toBe(true);
    expect(validateUrl("#some-heading")).toBe(true);
  });

  it("accepts www and bare-domain forms", () => {
    expect(validateUrl("www.example.com")).toBe(true);
    expect(validateUrl("example.com/path")).toBe(true);
  });
});

describe("sanitizeUrl link-insertion placeholder", () => {
  it("passes the https:// placeholder through unchanged", () => {
    // The floating link editor initialises/resets editedLinkUrl to "https://";
    // sanitizing it to about:blank would corrupt link insertion (PR review P1).
    expect(sanitizeUrl("https://")).toBe("https://");
  });
});
