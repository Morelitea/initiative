/**
 * Two frames are drawn rather than fetched, because their colours are not
 * decided until somebody decides them. What is worth pinning is that the
 * wearer's choice is what gets painted, and that everything else is still a
 * file.
 */
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";

const wearing = (frame: string, frameTint: string[] = []) =>
  render(
    <ProfileAvatar
      user={buildUser()}
      decorations={{ banner: null, frame, frame_tint: frameTint, trophies: [] }}
    />
  );

describe("a frame whose colours are the wearer's", () => {
  it("paints the two they picked", () => {
    const { container } = wearing("core.split", ["#112233", "#445566"]);

    const fills = [...container.querySelectorAll("rect")].map((rect) => rect.getAttribute("fill"));
    expect(fills).toContain("#112233");
    expect(fills).toContain("#445566");
  });

  it("falls back to its own colours where they picked none", () => {
    const { container } = wearing("core.split");

    const fills = [...container.querySelectorAll("rect")].map((rect) => rect.getAttribute("fill"));
    expect(fills).toContain("#1b5e32");
    expect(fills).toContain("#f2c230");
  });

  it("takes the first colour when the frame only has one", () => {
    const { container } = wearing("core.gold", ["#abcdef", "#000000"]);

    const fills = [...container.querySelectorAll("rect")].map((rect) => rect.getAttribute("fill"));
    expect(fills).toContain("#abcdef");
    expect(fills).not.toContain("#000000");
  });

  it("leaves every other frame as the file it is", () => {
    const { container } = wearing("spooky.web", ["#abcdef"]);

    expect(container.querySelector('img[src="/decorations/frames/spooky-web.svg"]')).not.toBeNull();
  });
});
