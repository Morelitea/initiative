/**
 * The pickers offer a library, not a catalog.
 *
 * What a person may wear is the server's answer, and these render it: one
 * picker per slot, showing what that account has and nothing else. The rules
 * worth pinning are the ones a reader would notice — a slot holds one thing,
 * the badge row holds several up to a cap, and a decoration this build has no
 * artwork for is left out rather than drawn as a blank tile.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { buildOwnedDecoration } from "@/__tests__/factories";

import { BadgePicker, SlotPicker } from "./DecorationPicker";

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

const badges = [
  buildOwnedDecoration({ id: "core.founder", kind: "badge" }),
  buildOwnedDecoration({ id: "core.storyteller", kind: "badge" }),
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
    expect(chosen).toHaveAttribute("aria-checked", "true");
    await userEvent.click(chosen);

    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("says so when the library has nothing for the slot", () => {
    render(<SlotPicker kind="frame" value={null} onChange={vi.fn()} owned={banners} />);

    expect(screen.getByText("decorationPicker.empty")).toBeInTheDocument();
  });
});

describe("the badge row", () => {
  it("wears them in the order they were picked", async () => {
    const onChange = vi.fn();
    render(<BadgePicker value={["core.storyteller"]} onChange={onChange} owned={badges} max={6} />);

    await userEvent.click(screen.getByRole("checkbox", { name: "decorations.founder" }));

    expect(onChange).toHaveBeenCalledWith(["core.storyteller", "core.founder"]);
  });

  it("takes one off when it is picked again", async () => {
    const onChange = vi.fn();
    render(<BadgePicker value={["core.founder"]} onChange={onChange} owned={badges} max={6} />);

    await userEvent.click(screen.getByRole("checkbox", { name: "decorations.founder" }));

    expect(onChange).toHaveBeenCalledWith([]);
  });

  it("stops at the cap rather than dropping what is already worn", async () => {
    // What is on is the reader's choice; the picker must not quietly evict the
    // oldest badge to make room for a new one.
    const onChange = vi.fn();
    render(<BadgePicker value={["core.storyteller"]} onChange={onChange} owned={badges} max={1} />);

    await userEvent.click(screen.getByRole("checkbox", { name: "decorations.founder" }));

    expect(onChange).not.toHaveBeenCalled();
  });
});
