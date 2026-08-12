/**
 * Where a placed widget's data comes from.
 *
 * Two modes, and the difference is a boundary rather than a preference. A
 * widget on a real dashboard resolves its binding through the ordinary
 * RLS-gated hooks, scoped to that dashboard's initiative. A widget in the
 * marketplace preview draws the sample library instead: the listing is not
 * installed, so it has no initiative to read and must be given none — which is
 * what these pin, at the seam where it would regress.
 */
import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import type { WidgetBinding } from "@/hooks/useWidgetData";
import { emptyDataFor } from "@/lib/widgets/normalize";

const useWidgetData = vi.hoisted(() => vi.fn());
vi.mock("@/hooks/useWidgetData", () => ({ useWidgetData }));

import { DashboardWidget } from "./DashboardWidget";

const widget = { id: "w1", type: "stat", grid: { x: 0, y: 0, w: 3, h: 2 } };
const binding: WidgetBinding = { source: "counter" };

const render = (sampleData: boolean) => {
  useWidgetData.mockReturnValue({
    data: emptyDataFor("counter"),
    isLoading: false,
    isUnbound: true,
  });
  renderWithProviders(
    <DashboardWidget
      widget={widget}
      binding={binding}
      initiativeId={7}
      canEdit={false}
      sampleData={sampleData}
    />
  );
};

describe("DashboardWidget", () => {
  it("resolves the binding against the dashboard's initiative", () => {
    render(false);
    expect(useWidgetData).toHaveBeenCalledWith(binding, 7);
  });

  it("reads no initiative at all in sample mode", () => {
    // The hook still runs — hooks are unconditional — but without an
    // initiative it fail-closes and issues no request. This is what keeps an
    // uninstalled listing's preview from touching the guild's data.
    render(true);
    expect(useWidgetData).toHaveBeenCalledWith(binding, undefined);
  });

  it("draws the sample library rather than the resolved binding", async () => {
    // The hook is returning an *unbound* envelope, which on a real dashboard
    // renders the "configure me" notice. In sample mode the tile draws the
    // sample instead, so the counter's name proves where the rows came from.
    render(true);
    expect(await screen.findByText("Beds made")).toBeInTheDocument();
    expect(screen.queryByText(/choose what this widget shows/i)).toBeNull();
  });
});
