import { Paperclip, Waypoints } from "lucide-react";
import { describe, expect, it } from "vitest";

import { iconDataUri, iconSvg } from "@/lib/iconSvg";

describe("iconSvg", () => {
  it("draws the icon that was asked for, in the colour asked for", () => {
    const markup = iconSvg(Paperclip, "#0ea5e9");
    expect(markup).toBeTruthy();
    expect(markup).toMatch(/^<svg /);
    expect(markup).toContain('stroke="#0ea5e9"');
    // The paths are the icon: an <svg> with nothing in it is a blank node.
    expect(markup).toContain("<path");
  });

  it("spells SVG attributes the way SVG spells them", () => {
    const markup = iconSvg(Waypoints, "#000000") ?? "";
    // Kebab where SVG is kebab...
    expect(markup).toContain("stroke-width=");
    expect(markup).toContain("stroke-linecap=");
    // ...and camel where SVG is camel. `viewbox` is not a thing.
    expect(markup).toContain("viewBox=");
    expect(markup).not.toContain("viewbox=");
  });

  it("tells two icons apart", () => {
    expect(iconSvg(Paperclip, "#000")).not.toBe(iconSvg(Waypoints, "#000"));
  });

  it("says nothing rather than throwing at something it does not understand", () => {
    const NotAnIcon = () => null;
    expect(iconSvg(NotAnIcon, "#000")).toBeNull();
    expect(iconDataUri(NotAnIcon, "#000")).toBeNull();
  });

  it("gives something an image can load", () => {
    const uri = iconDataUri(Paperclip, "#0ea5e9") ?? "";
    expect(uri).toMatch(/^data:image\/svg\+xml;charset=utf-8,/);
    expect(decodeURIComponent(uri.split(",")[1])).toMatch(/^<svg /);
  });
});
