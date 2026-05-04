import { describe, expect, it } from "vitest";

import { sanitizeEmbedHtml } from "./embed-node";

/**
 * Legacy EmbedNode renders stored HTML via dangerouslySetInnerHTML, so
 * any document loaded through importJSON could otherwise execute
 * attacker-controlled markup. These cases pin the sanitization contract
 * we rely on at the constructor boundary.
 */
describe("sanitizeEmbedHtml", () => {
  it("strips <script> tags", () => {
    const result = sanitizeEmbedHtml("<script>window.x=1</script><p>safe</p>");
    expect(result).not.toContain("<script");
    expect(result).not.toContain("window.x=1");
    expect(result).toContain("<p>safe</p>");
  });

  it("strips inline event-handler attributes", () => {
    const result = sanitizeEmbedHtml('<img src="x" onerror="alert(1)" />');
    expect(result).not.toContain("onerror");
    expect(result).not.toContain("alert(1)");
  });

  it("strips javascript: URLs from anchors", () => {
    const result = sanitizeEmbedHtml('<a href="javascript:alert(1)">click</a>');
    expect(result).not.toContain("javascript:");
  });

  it("preserves benign formatting markup", () => {
    const result = sanitizeEmbedHtml("<p><b>hello</b> <i>world</i></p>");
    expect(result).toBe("<p><b>hello</b> <i>world</i></p>");
  });

  it("handles empty input", () => {
    expect(sanitizeEmbedHtml("")).toBe("");
  });
});
