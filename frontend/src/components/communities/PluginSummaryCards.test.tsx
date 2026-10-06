import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";

const SUMMARY = "plugin.acme.meter.standing";

const state = vi.hoisted(() => ({
  plugins: [] as unknown[],
  values: {} as Record<string, unknown> | undefined,
  error: false,
  asked: [] as number[],
}));

vi.mock("@/hooks/useActiveCommunityId", () => ({ useActiveCommunityId: () => 7 }));
vi.mock("@/hooks/useCommunityPlugins", () => ({
  useCommunityPlugins: () => ({ data: { items: state.plugins } }),
}));
vi.mock("@/api/generated/plugins/plugins", () => ({
  useReadPluginSummary: (_communityId: number, pluginId: number) => {
    state.asked.push(pluginId);
    return {
      data: state.values === undefined ? undefined : { values: state.values },
      isError: state.error,
    };
  },
}));

import { PluginSummaryCards } from "./PluginSummaryCards";

const plugin = (overrides: Record<string, unknown> = {}) => ({
  id: 3,
  name: "Meter",
  enabled: true,
  definition: {
    community_summary: SUMMARY,
    endpoints: [
      {
        id: SUMMARY,
        direction: "read",
        returns: [
          { key: "used", type: "int", label: { en: "Runs this month" }, of: "allowed" },
          { key: "allowed", type: "int", label: { en: "Monthly allowance" } },
          { key: "left", type: "int", label: { en: "Credits left" } },
          { key: "resets_on", type: "datetime", label: { en: "Resets" } },
        ],
      },
    ],
  },
  ...overrides,
});

describe("PluginSummaryCards", () => {
  beforeEach(() => {
    state.plugins = [plugin()];
    state.values = { used: 250, allowed: 500, left: 1500, resets_on: "2026-11-15T12:00:00Z" };
    state.error = false;
    state.asked = [];
  });

  it("draws each figure under the plug-in's own label, a pair as one measure", () => {
    renderWithProviders(<PluginSummaryCards />);
    expect(screen.getByText("Meter")).toBeInTheDocument();
    expect(screen.getByText("Runs this month")).toBeInTheDocument();
    expect(screen.getByText("250 of 500")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toBeInTheDocument();
    // The ceiling is inside the measure, not a row of its own.
    expect(screen.queryByText("Monthly allowance")).not.toBeInTheDocument();
    expect(screen.getByText("Credits left")).toBeInTheDocument();
    expect(screen.getByText("1,500")).toBeInTheDocument();
    expect(screen.getByText("November 15, 2026")).toBeInTheDocument();
  });

  it("draws a figure with no ceiling alone", () => {
    state.values = { used: 250, allowed: null, left: 0 };
    renderWithProviders(<PluginSummaryCards />);
    expect(screen.getByText("250")).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("says a plug-in that does not answer is unavailable", () => {
    state.values = undefined;
    state.error = true;
    renderWithProviders(<PluginSummaryCards />);
    expect(screen.getByText("Meter")).toBeInTheDocument();
    expect(screen.getByText("Unavailable right now")).toBeInTheDocument();
  });

  it("asks nothing of a plug-in that names no summary, or is switched off", () => {
    state.plugins = [
      plugin({ id: 4, definition: { endpoints: [] } }),
      plugin({ id: 5, enabled: false }),
    ];
    renderWithProviders(<PluginSummaryCards />);
    expect(state.asked).toEqual([]);
    expect(screen.queryByText("Meter")).not.toBeInTheDocument();
  });
});
