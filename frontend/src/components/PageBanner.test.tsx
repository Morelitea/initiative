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

  it("takes the readable side of the contrast over a colour", () => {
    const { rerender } = render(<PageBanner color="#101010" title="Dark" />);
    expect(screen.getByRole("heading", { name: "Dark" })).toHaveClass("text-white");

    rerender(<PageBanner color="#f5f0e8" title="Light" />);
    expect(screen.getByRole("heading", { name: "Light" })).toHaveClass("text-neutral-900");
  });

  it("keeps the halo over artwork, where there is detail to see through", () => {
    render(<PageBanner imageUrl="/images/banner.webp" title="Communities" />);

    expect(screen.getByRole("heading", { name: "Communities" }).className).toContain("text-shadow");
  });
});
