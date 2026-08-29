import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PageBanner } from "./PageBanner";

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
    expect(container.firstElementChild).toHaveStyle({ backgroundColor: "rgb(42, 157, 143)" });
  });

  it("prefers the picture when a guild has set both", () => {
    const { container } = render(
      <PageBanner imageUrl="/api/v1/guilds/1/image/abc" color="#2a9d8f" title="Ravenloft" />
    );

    expect(container.querySelector("img")).toHaveAttribute("src", "/api/v1/guilds/1/image/abc");
    // The colour is the alternative, not a backdrop, so it is not painted too.
    expect(container.firstElementChild).not.toHaveStyle({ backgroundColor: "rgb(42, 157, 143)" });
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
});
