import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PageBanner } from "./PageBanner";

/** The fill and the artwork live on a layer under the copy, so the fade can be
 *  applied to one without touching the other. */
const ground = (container: HTMLElement) =>
  container.firstElementChild?.firstElementChild as HTMLElement;

/** jsdom drops `mask-image` from a style declaration entirely, so the gradient
 *  itself is not assertable here. Everything it is derived from is: the extra
 *  row, the margin that gives it back, and which layer carries the fade. */
const fadeRow = (container: HTMLElement) =>
  (container.firstElementChild as HTMLElement).style.gridTemplateRows;

describe("PageBanner", () => {
  it("shows the picture when there is one, and nothing to see through the copy", () => {
    render(<PageBanner imageUrl="/images/banner.webp" title="Communities" subtitle="Find one" />);

    const image = screen.getByRole("presentation", { hidden: true });
    expect(image).toHaveAttribute("src", "/images/banner.webp");
    expect(screen.getByRole("heading", { name: "Communities" })).toBeInTheDocument();
    expect(screen.getByText("Find one")).toBeInTheDocument();
  });

  it("falls back to the colour when there is no picture", () => {
    const { container } = render(<PageBanner color="#2a9d8f" title="Ravenloft" />);

    expect(container.querySelector("img")).toBeNull();
    expect(ground(container)).toHaveStyle({ backgroundColor: "rgb(42, 157, 143)" });
  });

  it("prefers the picture when a guild has set both", () => {
    const { container } = render(
      <PageBanner imageUrl="/api/v1/guilds/1/image/abc" color="#2a9d8f" title="Ravenloft" />
    );

    expect(container.querySelector("img")).toHaveAttribute("src", "/api/v1/guilds/1/image/abc");
    // The colour is the alternative, not a backdrop, so it is not painted too.
    expect(ground(container)).not.toHaveStyle({ backgroundColor: "rgb(42, 157, 143)" });
  });

  it("takes the readable side of the contrast when no text colour is given", () => {
    const { rerender } = render(<PageBanner color="#101010" title="Dark" />);
    expect(screen.getByRole("heading", { name: "Dark" })).toHaveStyle({ color: "#ffffff" });

    rerender(<PageBanner color="#f5f0e8" title="Light" />);
    expect(screen.getByRole("heading", { name: "Light" })).toHaveStyle({ color: "#000000" });
  });

  it("uses the text colour it is given, including over artwork", () => {
    render(
      <PageBanner imageUrl="/api/v1/guilds/1/image/abc" textColor="#000000" title="Ravenloft" />
    );

    expect(screen.getByRole("heading", { name: "Ravenloft" })).toHaveStyle({ color: "#000000" });
  });

  it("backs the copy with a shadow of the opposite tone", () => {
    // The stored text colour is one answer for a banner whose brightness
    // varies across it, so the words carry their own contrast behind them.
    const { rerender } = render(<PageBanner color="#101010" title="Ravenloft" />);
    expect(screen.getByRole("heading", { name: "Ravenloft" }).style.textShadow).toContain(
      "rgba(0,0,0"
    );

    rerender(<PageBanner color="#f5f0e8" title="Ravenloft" />);
    expect(screen.getByRole("heading", { name: "Ravenloft" }).style.textShadow).toContain(
      "rgba(255,255,255"
    );
  });

  it("keeps the halo only where it is asked for, over fixed artwork", () => {
    render(<PageBanner imageUrl="/images/banner.webp" haloOverImage title="Communities" />);

    expect(screen.getByRole("heading", { name: "Communities" }).className).toContain("text-shadow");
  });

  it("is a short band with only a colour, and a tall one with a picture", () => {
    const { container, rerender } = render(<PageBanner color="#2563eb" title="Ravenloft" />);
    const band = container.querySelector("h1")?.parentElement;
    expect(band?.className).toContain("min-h-28");

    rerender(<PageBanner imageUrl="/images/banner.webp" title="Ravenloft" />);
    expect(container.querySelector("h1")?.parentElement?.className).toContain("min-h-[85vw]");
  });

  it("centres the copy unless it is asked to align it left", () => {
    const { container, rerender } = render(<PageBanner color="#2563eb" title="Ravenloft" />);
    expect(container.querySelector("h1")?.parentElement?.className).toContain("text-center");

    rerender(<PageBanner color="#2563eb" align="left" title="Ravenloft" />);
    const copy = container.querySelector("h1")?.parentElement;
    expect(copy?.className).toContain("text-left");
    expect(copy?.className).toContain("items-start");
  });

  it("does not fade, extend, or take back any margin unless asked to", () => {
    const { container } = render(<PageBanner color="#2563eb" title="Ravenloft" />);

    const banner = container.firstElementChild as HTMLElement;
    expect(banner.style.marginBottom).toBe("");
    expect(fadeRow(container)).toBe("");
    expect(ground(container).style.gridRow).toBe("1");
  });

  it("fades into the page and takes back exactly what it added", () => {
    // Adding a row and removing the same margin is what puts the page's own
    // content over the banner's tail without moving anything else.
    const { container } = render(
      <PageBanner color="#2563eb" fade="strong" title="Ravenloft" subtitle="A guild" />
    );

    const banner = container.firstElementChild as HTMLElement;
    expect(fadeRow(container)).toBe("auto 224px");
    expect(banner.style.marginBottom).toBe("-224px");
    // The ground spans both rows — the fade band is as much banner as the
    // rest of it — while the copy sits in the first row alone and stays opaque.
    expect(ground(container).style.gridRow).toBe("1 / span 2");
    expect(container.querySelector("h1")?.parentElement?.style.gridRow).toBe("1");
  });

  it("fades over a shorter tail on the weaker setting", () => {
    const { container } = render(<PageBanner color="#2563eb" fade="weak" title="Ravenloft" />);

    const banner = container.firstElementChild as HTMLElement;
    expect(fadeRow(container)).toBe("auto 48px");
    expect(banner.style.marginBottom).toBe("-48px");
  });

  it("puts the badges in the corner, out of the copy it is not part of", () => {
    const { container, rerender } = render(<PageBanner color="#2563eb" title="Ravenloft" />);
    expect(screen.queryByText("11 members")).not.toBeInTheDocument();

    rerender(<PageBanner color="#2563eb" title="Ravenloft" badges={<span>11 members</span>} />);
    const corner = screen.getByText("11 members").parentElement;
    expect(corner?.className).toContain("top-4");
    expect(corner?.className).toContain("right-4");
    // Not inside the heading's box — the counts are about the banner, not
    // something it says.
    expect(container.querySelector("h1")?.parentElement).not.toBe(corner);
  });

  it("covers the banner with the picture rather than letting it set the height", () => {
    // A picture sized to its own 4:1 would stop above a fade's band and leave
    // it empty — a hard edge over nothing, which is not a fade.
    render(<PageBanner imageUrl="/images/banner.webp" fade="strong" title="Ravenloft" />);

    const image = screen.getByRole("presentation", { hidden: true });
    expect(image.className).toContain("object-cover");
    expect(image.className).toContain("inset-0");
    expect(image.className).toContain("h-full");
  });
});
