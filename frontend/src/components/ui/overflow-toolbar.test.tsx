import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  OverflowMenuItem,
  OverflowSubmenu,
  OverflowToolbar,
  type OverflowToolbarItem,
} from "@/components/ui/overflow-toolbar";

const ITEM_WIDTH = 100;

/** The measured row is the one child carrying `overflow-hidden`. */
const isRow = (el: HTMLElement) => el.classList.contains("overflow-hidden");

/**
 * jsdom lays nothing out: every element measures zero. Give the row and the
 * wrappers inside it the widths a browser would, so the shedding rule is what
 * the test exercises rather than the "nothing to read, show everything"
 * fallback. Must be in place before the first layout effect runs.
 */
const stubLayout = (rowWidth: number) => {
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockImplementation(function (
    this: HTMLElement
  ) {
    return isRow(this) ? rowWidth : 0;
  });
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockImplementation(function (
    this: HTMLElement
  ) {
    const parent = this.parentElement;
    return parent && isRow(parent) ? ITEM_WIDTH : 0;
  });
};

const buildItems = (count: number): OverflowToolbarItem[] =>
  Array.from({ length: count }, (_, index) => ({
    id: `item-${index}`,
    node: <button type="button">{`Action ${index}`}</button>,
    menu: <OverflowMenuItem>{`Action ${index}`}</OverflowMenuItem>,
  }));

const renderToolbar = (items: OverflowToolbarItem[]) =>
  render(<OverflowToolbar items={items} label="Test toolbar" moreLabel="More" />);

const rowChildren = (container: HTMLElement) =>
  Array.from(container.querySelector(".overflow-hidden")?.children ?? []) as HTMLElement[];

describe("OverflowToolbar", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("keeps every item in the row when there is no layout to measure", () => {
    const { container } = renderToolbar(buildItems(6));

    expect(rowChildren(container).filter((child) => child.hidden)).toHaveLength(0);
    expect(screen.getByRole("button", { name: "More", hidden: true })).not.toBeVisible();
  });

  it("sheds the items that do not fit, from the right", async () => {
    // Three of six 100px items fit in a 320px row (jsdom reports no gap).
    stubLayout(320);
    const { container } = renderToolbar(buildItems(6));

    await waitFor(() => {
      expect(rowChildren(container).filter((child) => child.hidden)).toHaveLength(3);
    });

    const shown = rowChildren(container).filter((child) => !child.hidden);
    expect(shown.map((child) => child.textContent)).toEqual(["Action 0", "Action 1", "Action 2"]);

    const more = screen.getByRole("button", { name: "More" });
    expect(more).toBeVisible();

    await userEvent.click(more);
    expect(await screen.findByRole("menuitem", { name: "Action 5" })).toBeInTheDocument();
  });

  it("names a shed control in the menu", async () => {
    stubLayout(100);
    renderToolbar([
      {
        id: "stays",
        node: <button type="button">Stays</button>,
        menu: <OverflowMenuItem>Stays</OverflowMenuItem>,
      },
      {
        id: "goes",
        node: <button type="button" aria-label="Rarely needed" />,
        menu: <OverflowMenuItem>Rarely needed</OverflowMenuItem>,
      },
    ]);

    await userEvent.click(await screen.findByRole("button", { name: "More" }));

    // The row shows an icon; the menu has room to say what it does.
    expect(await screen.findByRole("menuitem", { name: "Rarely needed" })).toBeInTheDocument();
  });

  it("keeps a menu-only item out of the row however wide it is", async () => {
    const items: OverflowToolbarItem[] = [
      ...buildItems(2),
      {
        id: "hidden-one",
        node: <button type="button">Rarely</button>,
        menu: <OverflowMenuItem>Rarely</OverflowMenuItem>,
        menuOnly: true,
      },
    ];

    const { container } = renderToolbar(items);

    // Two items in the row; the third is only ever reachable from the panel.
    expect(rowChildren(container)).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Rarely" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "More" }));
    expect(await screen.findByRole("menuitem", { name: "Rarely" })).toBeInTheDocument();
  });
});

describe("the overflow menu's branches", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("drills into a branch and back, rather than flying out beside the menu", async () => {
    // Narrower than one item: both shed, so both are in the menu.
    stubLayout(10);
    renderToolbar([
      {
        id: "stays",
        node: <button type="button">Stays</button>,
        menu: <OverflowMenuItem>Stays</OverflowMenuItem>,
      },
      {
        id: "colors",
        node: <button type="button" aria-label="Colours" />,
        menu: (
          <OverflowSubmenu id="colors" label="Colours">
            <OverflowMenuItem>Red</OverflowMenuItem>
          </OverflowSubmenu>
        ),
      },
    ]);

    await userEvent.click(await screen.findByRole("button", { name: "More" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: /Colours/ }));

    // The branch replaces the menu: what was above it is gone while it is open.
    expect(await screen.findByRole("menuitem", { name: "Red" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Stays" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("menuitem", { name: /Colours/ }));
    expect(await screen.findByRole("menuitem", { name: "Stays" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Red" })).not.toBeInTheDocument();
  });
});
