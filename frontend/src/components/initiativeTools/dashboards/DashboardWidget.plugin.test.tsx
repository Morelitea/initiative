/**
 * A plug-in's widget on a dashboard: where its template comes from, and what
 * happens when the plug-in behind it does not answer.
 *
 * Three things are pinned here.
 *
 * **A preview issues zero requests.** A marketplace listing that is not
 * installed must render from what the manifest shipped — its own template over
 * its own sample — and reach nothing at all. The assertion is on the transport:
 * not "it used samples", but "no request was made".
 *
 * **The template comes from the pinned definition.** A plug-in widget is not in
 * this build's registry; its template arrives with the install and is drawn with
 * the same elements a built-in uses. `WidgetTile.plugin` is that seam, and this
 * checks it is actually threaded rather than falling back to the registry (which
 * would silently render "this widget needs a newer version").
 *
 * **An unreachable plug-in costs one tile.** Not a crash, not a blank, not a
 * misleading "no data" — a localized error tile, with the rest of the canvas
 * untouched.
 */
import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import type { WidgetBinding } from "@/hooks/useWidgetData";
import type { DefinitionWidget } from "@/lib/widgets/definition";
import { WidgetErrorCode } from "@/lib/widgets/errors";

const apiGet = vi.hoisted(() => vi.fn());
vi.mock("@/api/client", () => ({
  apiClient: { get: apiGet, post: vi.fn(), put: vi.fn(), delete: vi.fn() },
  API_BASE_URL: "http://test/api/v1",
}));

import { DashboardWidget } from "./DashboardWidget";

const PLUGIN_UID = "SHOPAPP0000001";
const WIDGET_TYPE = `plugin:${PLUGIN_UID}:summary`;
const TEMPLATE = '<metric :value="values.total" :label="strings.total" />';

const binding: WidgetBinding = {
  source: "plugin",
  plugin_uid: PLUGIN_UID,
  endpoint_id: "plugin.acme.shop.orders-summary",
};
const widget: DefinitionWidget = {
  id: "w1",
  type: WIDGET_TYPE,
  grid: { x: 0, y: 0, w: 6, h: 4 },
  binding,
};

const CATALOG = {
  items: [
    {
      plugin_id: 3,
      plugin_uid: PLUGIN_UID,
      name: "Shop",
      enabled: true,
      widgets: [
        {
          type: WIDGET_TYPE,
          id: "summary",
          meta: { name: { en: "Summary" } },
          endpoint: "plugin.acme.shop.orders-summary",
          template: TEMPLATE,
          strings: { total: { en: "Orders this week" } },
          sample_data: { rows: [{ days: "mon", totals: 4 }], values: { total: 4 } },
        },
      ],
      endpoints: [
        {
          id: "plugin.acme.shop.orders-summary",
          cache_ttl_seconds: 60,
          params: [],
          returns: [
            { key: "days", type: "string", list: true },
            { key: "totals", type: "int", list: true },
            { key: "total", type: "int" },
          ],
        },
      ],
    },
  ],
};

const catalogUrl = (url: string) => url.endsWith("/plugins/widget-catalog");
const dataUrl = (url: string) => url.includes("/endpoints/");

beforeEach(() => {
  apiGet.mockReset();
});

const mount = (props: { sampleData?: boolean; dashboardId?: number } = {}) =>
  renderWithProviders(
    <DashboardWidget
      widget={widget}
      binding={binding}
      initiativeId={props.sampleData ? undefined : 7}
      dashboardId={props.dashboardId}
      canEdit={false}
      sampleData={props.sampleData}
    />,
    { communities: { activeCommunityId: 2 } }
  );

describe("DashboardWidget with a plug-in source", () => {
  it("draws the template the install pinned, over the answer the proxy returned", async () => {
    apiGet.mockImplementation((url: string) => {
      if (catalogUrl(url)) return Promise.resolve({ data: CATALOG });
      if (dataUrl(url)) {
        return Promise.resolve({
          data: {
            rows: [{ days: "mon", totals: 9 }],
            values: { total: 9 },
            fetched_at: "",
            cached: false,
          },
        });
      }
      return Promise.resolve({ data: {} });
    });

    mount({ dashboardId: 11 });

    // The seam: the template comes from the pinned definition, not the
    // registry, and reads the live answer and the widget's own words.
    expect(await screen.findByText("Orders this week")).toBeInTheDocument();
    expect(screen.getByText("9")).toBeInTheDocument();
  });

  it("asks the proxy for the dashboard the widget sits on", async () => {
    apiGet.mockImplementation((url: string) =>
      Promise.resolve({
        data: catalogUrl(url) ? CATALOG : { rows: [], values: {}, fetched_at: "", cached: false },
      })
    );

    mount({ dashboardId: 11 });

    await waitFor(() => expect(apiGet.mock.calls.some(([url]) => dataUrl(url))).toBe(true));
    const [url, config] = apiGet.mock.calls.find(([u]) => dataUrl(u)) as [
      string,
      { params: Record<string, unknown> },
    ];
    expect(url).toBe("/c/2/plugins/3/endpoints/plugin.acme.shop.orders-summary");
    expect(config.params.dashboard_id).toBe(11);
  });

  it("draws an error tile when the plug-in is not answering", async () => {
    apiGet.mockImplementation((url: string) => {
      if (catalogUrl(url)) return Promise.resolve({ data: CATALOG });
      return Promise.reject(new Error("502"));
    });

    mount({ dashboardId: 11 });

    expect(await screen.findByText(/not responding/i)).toBeInTheDocument();
    // The template is never drawn: it has nothing to read, and drawing it over
    // nothing would claim "no data" rather than "the plug-in is down".
    expect(screen.queryByText("Orders this week")).toBeNull();
  });

  it("previews from the manifest's own samples and issues zero requests", async () => {
    apiGet.mockImplementation((url: string) =>
      catalogUrl(url)
        ? Promise.resolve({ data: CATALOG })
        : Promise.reject(new Error("a preview must not fetch data"))
    );

    mount({ sampleData: true });

    expect(await screen.findByText("Orders this week")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
    // The catalog is a declaration; the data plane is never touched.
    expect(apiGet.mock.calls.every(([url]) => catalogUrl(url))).toBe(true);
  });

  it("has a localized message for the failure it can produce", () => {
    expect(WidgetErrorCode.PLUGIN_UNAVAILABLE).toBe("WIDGET_PLUGIN_UNAVAILABLE");
  });

  it("asks for the plug-in to be reconnected when the catalog no longer lists it", async () => {
    // The definition is kept as-is when its plug-in goes away; the tile is the
    // surface that says so. Distinct from both the restricted state (this is
    // not an access outcome) and the unavailable state (the catalog answered).
    apiGet.mockImplementation((url: string) => {
      if (catalogUrl(url)) return Promise.resolve({ data: { items: [] } });
      return Promise.reject(new Error("nothing should be fetched for it"));
    });

    mount({ dashboardId: 11 });

    expect(await screen.findByText(/no longer installed/i)).toBeInTheDocument();
    // Only the catalog was read; the data plane was never asked.
    expect(apiGet.mock.calls.every(([url]) => catalogUrl(url))).toBe(true);
  });

  it("says its template cannot be drawn when this build will not compile it", async () => {
    // Checked when the plug-in was published, so this is a build whose template
    // language moved on. One tile says so, with the compiler's own reason.
    const stale = structuredClone(CATALOG);
    stale.items[0].widgets[0].template = '<metric :value="values.gone" />';
    apiGet.mockImplementation((url: string) => {
      if (catalogUrl(url)) return Promise.resolve({ data: stale });
      return Promise.resolve({ data: { rows: [], values: {}, fetched_at: "", cached: false } });
    });

    mount({ dashboardId: 11 });

    expect(await screen.findByText(/template could not be drawn/i)).toBeInTheDocument();
    expect(screen.getByText(/There is no field gone here/)).toBeInTheDocument();
  });

  it("says the plug-in is unavailable when its catalog will not load", async () => {
    // A catalog that failed says nothing about whether the plug-in is installed.
    // Reading it as "not installed" would mark every plug-in widget on the board
    // unconfigured and invite someone to repoint bindings that were never wrong.
    apiGet.mockImplementation(() => Promise.reject(new Error("503")));

    mount({ dashboardId: 11 });

    expect(await screen.findByText(/not responding/i)).toBeInTheDocument();
    expect(screen.queryByText(/not configured/i)).toBeNull();
  });
});
