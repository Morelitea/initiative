import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import { Lightbox, type LightboxItem } from "@/components/shared/Lightbox";

const items: LightboxItem[] = [
  { id: 1, src: "/uploads/1/a.png", alt: "First" },
  { id: 2, src: "/uploads/1/b.png", alt: "Second" },
  { id: 3, src: "/uploads/1/c.png", alt: "Third" },
];

describe("Lightbox", () => {
  it("shows the picture at the index and where it is in the set", () => {
    renderWithProviders(
      <Lightbox open onOpenChange={() => {}} items={items} index={1} onIndexChange={() => {}} />
    );
    expect(screen.getByRole("img", { name: "Second" })).toBeInTheDocument();
    expect(screen.getByText("2 / 3")).toBeInTheDocument();
  });

  it("pages with the arrow keys and the chevrons", () => {
    const onIndexChange = vi.fn();
    renderWithProviders(
      <Lightbox
        open
        onOpenChange={() => {}}
        items={items}
        index={1}
        onIndexChange={onIndexChange}
      />
    );
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(onIndexChange).toHaveBeenLastCalledWith(2);
    fireEvent.keyDown(window, { key: "ArrowLeft" });
    expect(onIndexChange).toHaveBeenLastCalledWith(0);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(onIndexChange).toHaveBeenLastCalledWith(2);
  });

  it("offers no way past either end", () => {
    const onIndexChange = vi.fn();
    renderWithProviders(
      <Lightbox
        open
        onOpenChange={() => {}}
        items={items}
        index={0}
        onIndexChange={onIndexChange}
      />
    );
    expect(screen.queryByRole("button", { name: "Previous" })).not.toBeInTheDocument();
    fireEvent.keyDown(window, { key: "ArrowLeft" });
    expect(onIndexChange).not.toHaveBeenCalled();
  });

  it("a single picture is just a picture", () => {
    renderWithProviders(
      <Lightbox
        open
        onOpenChange={() => {}}
        items={[items[0]]}
        index={0}
        onIndexChange={() => {}}
      />
    );
    expect(screen.queryByText(/\/ 1/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Next" })).not.toBeInTheDocument();
  });

  it("closes on a click beside the picture, not on the picture itself", () => {
    const onOpenChange = vi.fn();
    renderWithProviders(
      <Lightbox open onOpenChange={onOpenChange} items={items} index={1} onIndexChange={vi.fn()} />
    );
    // The content fills the overlay, so the dark around the picture is the
    // only backdrop there is — clicking it dismisses, the way clicking
    // outside any other dialog does.
    const picture = screen.getByRole("img", { name: "Second" });
    fireEvent.click(picture);
    expect(onOpenChange).not.toHaveBeenCalled();

    const stage = picture.parentElement as HTMLElement;
    fireEvent.click(stage);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("asks for more as the reader nears the end", () => {
    const onNearEnd = vi.fn();
    renderWithProviders(
      <Lightbox
        open
        onOpenChange={() => {}}
        items={items}
        index={2}
        onIndexChange={() => {}}
        onNearEnd={onNearEnd}
      />
    );
    expect(onNearEnd).toHaveBeenCalled();
  });
});
