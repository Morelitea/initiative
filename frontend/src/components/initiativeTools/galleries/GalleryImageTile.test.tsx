import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { buildGalleryImage } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import { GalleryImageTile } from "@/components/initiativeTools/galleries/GalleryImageTile";

const image = buildGalleryImage({ title: "Hero" });

describe("GalleryImageTile", () => {
  it("opens the picture when the wall is not selecting", () => {
    const onActivate = vi.fn();
    renderWithProviders(<GalleryImageTile image={image} onActivate={onActivate} />);
    fireEvent.click(screen.getByRole("button", { name: "Hero" }));
    expect(onActivate).toHaveBeenCalledWith({ extend: false });
  });

  it("asks for a range when the click held shift", () => {
    const onActivate = vi.fn();
    renderWithProviders(<GalleryImageTile image={image} onActivate={onActivate} selecting />);
    fireEvent.click(screen.getByRole("button", { name: "Hero" }), { shiftKey: true });
    expect(onActivate).toHaveBeenCalledWith({ extend: true });
  });

  it("says whether it is in the selection, and only while selecting", () => {
    const { rerender } = renderWithProviders(
      <GalleryImageTile image={image} onActivate={vi.fn()} selecting selected />
    );
    expect(screen.getByRole("button", { name: "Hero" })).toHaveAttribute("aria-pressed", "true");
    rerender(<GalleryImageTile image={image} onActivate={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Hero" })).not.toHaveAttribute("aria-pressed");
  });
});
