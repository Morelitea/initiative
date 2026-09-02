/**
 * The pickers offer a library, not a catalog.
 *
 * What a person may wear is the server's answer, and these render it: one
 * picker per slot, showing what that account has and nothing else. The rules
 * worth pinning are the ones a reader would notice — a slot holds one thing,
 * the trophy row holds several up to a cap, and a decoration this build has no
 * artwork for is left out rather than drawn as a blank tile.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { buildOwnedDecoration } from "@/__tests__/factories";

import { SlotPicker, TrophyPicker } from "./DecorationPicker";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) =>
      options ? `${key}:${JSON.stringify(options)}` : key,
  }),
}));

const banners = [
  buildOwnedDecoration({ id: "core.aurora", kind: "banner" }),
  buildOwnedDecoration({ id: "core.ember", kind: "banner" }),
];

const trophies = [
  buildOwnedDecoration({ id: "ttrpg.d20", kind: "trophy" }),
  buildOwnedDecoration({ id: "plants.morel", kind: "trophy" }),
];

describe("a slot that holds one thing", () => {
  it("offers what the library holds for that slot, and nothing from another", async () => {
    render(
      <SlotPicker
        kind="banner"
        value={null}
        onChange={vi.fn()}
        owned={[...banners, buildOwnedDecoration({ id: "core.gold", kind: "frame" })]}
      />
    );

    expect(screen.getAllByRole("radio")).toHaveLength(2);
    expect(screen.getByRole("radio", { name: "decorations.aurora" })).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: "decorations.gold" })).not.toBeInTheDocument();
  });

  it("leaves out a decoration this build cannot draw", async () => {
    // A pack the server knows about and this build has no artwork for. A tile
    // that renders as nothing is worse than no tile.
    render(
      <SlotPicker
        kind="banner"
        value={null}
        onChange={vi.fn()}
        owned={[...banners, buildOwnedDecoration({ id: "studio.holo", kind: "banner" })]}
      />
    );

    expect(screen.getAllByRole("radio")).toHaveLength(2);
  });

  it("takes the decoration off when the one already on is picked again", async () => {
    const onChange = vi.fn();
    render(<SlotPicker kind="banner" value="core.aurora" onChange={onChange} owned={banners} />);

    const chosen = screen.getByRole("radio", { name: "decorations.aurora" });
    expect(chosen).toBeChecked();
    await userEvent.click(chosen);

    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("groups a slot's tiles so they read as alternatives", () => {
    // Real radios sharing a name: the browser gives the group one tab stop and
    // arrow keys move within it, which is what a slot holding one thing means.
    render(<SlotPicker kind="banner" value={null} onChange={vi.fn()} owned={banners} />);

    for (const tile of screen.getAllByRole("radio")) {
      expect(tile).toHaveAttribute("name", "decoration-banner");
    }
  });

  it("says so when the library has nothing for the slot", () => {
    render(<SlotPicker kind="frame" value={null} onChange={vi.fn()} owned={banners} />);

    expect(screen.getByText("decorationPicker.empty")).toBeInTheDocument();
  });
});

describe("the trophy row", () => {
  it("wears them in the order they were picked", async () => {
    const onChange = vi.fn();
    render(<TrophyPicker value={["plants.morel"]} onChange={onChange} owned={trophies} max={6} />);

    await userEvent.click(screen.getByRole("checkbox", { name: "decorations.d20" }));

    expect(onChange).toHaveBeenCalledWith(["plants.morel", "ttrpg.d20"]);
  });

  it("takes one off when it is picked again", async () => {
    const onChange = vi.fn();
    render(<TrophyPicker value={["ttrpg.d20"]} onChange={onChange} owned={trophies} max={6} />);

    await userEvent.click(screen.getByRole("checkbox", { name: "decorations.d20" }));

    expect(onChange).toHaveBeenCalledWith([]);
  });

  it("marks a tile past the cap as unavailable rather than just inert", async () => {
    // Disabled says "not now" to a screen reader; an unresponsive tile says
    // nothing at all.
    render(<TrophyPicker value={["plants.morel"]} onChange={vi.fn()} owned={trophies} max={1} />);

    expect(screen.getByRole("checkbox", { name: "decorations.d20" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "decorations.morel" })).toBeEnabled();
  });

  it("stops at the cap rather than dropping what is already worn", async () => {
    // What is on is the reader's choice; the picker must not quietly evict the
    // oldest trophy to make room for a new one.
    const onChange = vi.fn();
    render(<TrophyPicker value={["plants.morel"]} onChange={onChange} owned={trophies} max={1} />);

    await userEvent.click(screen.getByRole("checkbox", { name: "decorations.d20" }));

    expect(onChange).not.toHaveBeenCalled();
  });
});
