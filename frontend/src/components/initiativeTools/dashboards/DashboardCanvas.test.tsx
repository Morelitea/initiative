/**
 * Canvas behaviour that only shows up in a render.
 *
 * The load-bearing one is the read-only case: arranging a dashboard is
 * authoring, so a viewer without DAC write must get a static grid and no
 * authoring affordances at all — not a disabled-looking one that still emits
 * layout changes.
 */
import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import type { WidgetCatalog } from "@/api/generated/initiativeAPI.schemas";
import {
  addWidget,
  type DashboardDefinition,
  EMPTY_DEFINITION,
  readConfig,
} from "@/lib/widgets/definition";

import { DashboardCanvas } from "./DashboardCanvas";

const catalog = {
  widgets: [
    {
      type: "kpi",
      min_w: 2,
      min_h: 2,
      default_w: 3,
      default_h: 2,
      sources: ["counter"],
      options: [],
    },
  ],
  presets: [],
} as unknown as WidgetCatalog;

const withKpi = (): DashboardDefinition => addWidget(EMPTY_DEFINITION, catalog, "kpi", "counter");

const render = (definition: DashboardDefinition, canEdit: boolean, onLayoutChange = vi.fn()) => {
  renderWithProviders(
    <DashboardCanvas
      definition={definition}
      config={readConfig({})}
      catalog={catalog}
      canEdit={canEdit}
      onLayoutChange={onLayoutChange}
    />
  );
  return onLayoutChange;
};

describe("DashboardCanvas", () => {
  it("invites the author to add a widget when the canvas is empty", () => {
    render(EMPTY_DEFINITION, true);
    expect(screen.getByText("This dashboard has no widgets yet.")).toBeInTheDocument();
    expect(screen.getByText("Add a widget to start showing your data.")).toBeInTheDocument();
  });

  it("tells a viewer without write access who can fill it instead", () => {
    render(EMPTY_DEFINITION, false);
    expect(screen.getByText("Someone with edit access can add widgets to it.")).toBeInTheDocument();
  });

  it("offers no authoring affordances without write access", () => {
    render(withKpi(), false);
    // The per-widget menu is the entry point to configure and remove; without
    // write there is nothing to open.
    expect(screen.queryByRole("button", { name: /options for/i })).toBeNull();
  });

  it("offers the widget menu with write access", () => {
    render(withKpi(), true);
    expect(screen.getByRole("button", { name: /options for/i })).toBeInTheDocument();
  });

  it("never reports a layout change for a read-only canvas", () => {
    const onLayoutChange = render(withKpi(), false);
    // Mount alone fires RGL's onLayoutChange; a static canvas must swallow it
    // rather than write the dashboard's row on someone else's behalf.
    expect(onLayoutChange).not.toHaveBeenCalled();
  });

  it("does not treat mounting as an edit", () => {
    const onLayoutChange = render(withKpi(), true);
    expect(onLayoutChange).not.toHaveBeenCalled();
  });
});
