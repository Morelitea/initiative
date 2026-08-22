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
import type { WidgetBinding, WidgetDataResult } from "@/hooks/useWidgetData";
import { WidgetErrorCode } from "@/lib/widgets/errors";
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
      dashboardId={11}
      canEdit={false}
      sampleData={sampleData}
    />
  );
};

describe("DashboardWidget", () => {
  it("resolves the binding against the dashboard's initiative", () => {
    render(false);
    expect(useWidgetData).toHaveBeenCalledWith(binding, 7, 11);
  });

  it("reads no initiative and no dashboard at all in sample mode", () => {
    // The hook still runs — hooks are unconditional — but without an
    // initiative it fail-closes and issues no request. The dashboard goes the
    // same way: an app source has nothing to address itself to, so a preview
    // cannot reach one either. This is what keeps an uninstalled listing's
    // preview from touching the guild's data.
    render(true);
    expect(useWidgetData).toHaveBeenCalledWith(binding, undefined, undefined);
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

/**
 * The three ways a widget can have nothing to draw.
 *
 * They used to be one notice, and they are three different messages to three
 * different people: an author who has not finished setting the widget up, a
 * reader whose access does not reach the data, and anyone at all when the
 * request simply failed. Collapsing them tells two of the three something
 * untrue.
 */
describe("a widget with nothing to draw", () => {
  const renderState = (result: Partial<WidgetDataResult>, widgetBinding = binding) => {
    useWidgetData.mockReturnValue({
      data: emptyDataFor("counter"),
      isLoading: false,
      isUnbound: false,
      isRestricted: false,
      refetch: vi.fn(),
      ...result,
    });
    renderWithProviders(
      <DashboardWidget
        widget={widget}
        binding={widgetBinding}
        initiativeId={7}
        dashboardId={11}
        canEdit={false}
      />
    );
  };

  it("asks for the missing choice when the binding was never finished", async () => {
    renderState({ isUnbound: true });
    expect(await screen.findByText(/choose what this shows/i)).toBeInTheDocument();
  });

  it("says the data is out of reach when the target resolved and is not there", async () => {
    renderState({ isRestricted: true }, { source: "counter", counter_group_id: 3, counter_id: 9 });
    expect(await screen.findByText(/can't see this widget's data/i)).toBeInTheDocument();
    // Nothing to configure here, so nothing invites a reader to repoint a
    // binding that was never wrong.
    expect(screen.queryByText(/choose what this shows/i)).toBeNull();
  });

  it("reports a failed fetch as a failure, not as an access decision", async () => {
    renderState(
      { errorCode: WidgetErrorCode.DATA_UNAVAILABLE },
      { source: "counter", counter_group_id: 3, counter_id: 9 }
    );
    expect(await screen.findByText(/could not be loaded/i)).toBeInTheDocument();
    expect(screen.queryByText(/can't see this widget's data/i)).toBeNull();
  });
});
