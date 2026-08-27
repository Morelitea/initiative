/**
 * An app's widget on a dashboard: where its module comes from, and what happens
 * when the app behind it does not answer.
 *
 * Three things are pinned here.
 *
 * **A preview issues zero requests.** A marketplace listing that is not
 * installed must render from what the manifest shipped — its own module over its
 * own sample rows — and reach nothing at all. The assertion is on the transport:
 * not "it used samples", but "no request was made".
 *
 * **The module comes from the pinned definition.** An app widget's code is not in
 * this build's registry; it arrives with the install and is handed to the same
 * sandbox a built-in runs in. `WidgetTile.source` is that seam, and this checks
 * it is actually threaded rather than falling back to the registry (which would
 * silently render "this widget needs a newer version").
 *
 * **An unreachable app costs one tile.** Not a crash, not a blank, not a
 * misleading "no data" — a localized error tile, with the rest of the canvas
 * untouched.
 */
import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import type { WidgetBinding } from "@/hooks/useWidgetData";
import { WidgetErrorCode } from "@/lib/widgets/errors";

const apiGet = vi.hoisted(() => vi.fn());
vi.mock("@/api/client", () => ({
  apiClient: { get: apiGet, post: vi.fn(), put: vi.fn(), delete: vi.fn() },
  API_BASE_URL: "http://test/api/v1",
}));

const renderWidget = vi.hoisted(() => vi.fn());
const readWidgetMeta = vi.hoisted(() => vi.fn());
vi.mock("@/lib/widgets/runtime/host", () => ({ renderWidget, readWidgetMeta }));

import { DashboardWidget } from "./DashboardWidget";

const APP_UID = "SHOPAPP0000001";
const WIDGET_TYPE = `app:${APP_UID}:summary`;
const MODULE = "export const render = () => ({ scene: { kind: 'empty' } });";

const widget = { id: "w1", type: WIDGET_TYPE, grid: { x: 0, y: 0, w: 6, h: 4 } };
const binding: WidgetBinding = {
  source: "app",
  app_uid: APP_UID,
  endpoint_id: "app.acme.shop.orders-summary",
};

const CATALOG = {
  items: [
    {
      app_id: 3,
      app_uid: APP_UID,
      name: "Shop",
      enabled: true,
      widgets: [
        {
          type: WIDGET_TYPE,
          id: "summary",
          meta: { name: { en: "Summary" } },
          module_source: MODULE,
          endpoints: ["app.acme.shop.orders-summary"],
          sample_data: { "app.acme.shop.orders-summary": [{ day: "mon", total: 4 }] },
        },
      ],
      endpoints: [
        {
          id: "app.acme.shop.orders-summary",
          visibility: "member",
          cache_ttl_seconds: 60,
          params: [],
        },
      ],
    },
  ],
};

const catalogUrl = (url: string) => url.endsWith("/apps/widget-catalog");
const dataUrl = (url: string) => url.includes("/endpoints/");

beforeEach(() => {
  apiGet.mockReset();
  renderWidget.mockReset();
  readWidgetMeta.mockReset();
  renderWidget.mockResolvedValue({ ok: true, spec: { scene: { kind: "empty" } } });
  readWidgetMeta.mockResolvedValue({ name: { en: "Summary" } });
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
    { guilds: { activeGuildId: 2 } }
  );

describe("DashboardWidget with an app source", () => {
  it("runs the module the install pinned, over the rows the proxy returned", async () => {
    apiGet.mockImplementation((url: string) => {
      if (catalogUrl(url)) return Promise.resolve({ data: CATALOG });
      if (dataUrl(url)) {
        return Promise.resolve({
          data: { rows: [{ day: "mon", total: 9 }], fetched_at: "", cached: false },
        });
      }
      return Promise.resolve({ data: {} });
    });

    mount({ dashboardId: 11 });

    await waitFor(() => expect(renderWidget).toHaveBeenCalled());
    const call = renderWidget.mock.calls.at(-1)?.[0];
    // The seam: the module comes from the pinned definition, not the registry.
    expect(call.source).toBe(MODULE);
    // Rows verbatim, plus the host's own count of them — nothing on this side
    // reads inside an app's rows.
    expect(call.data).toEqual({
      source: "app",
      rows: [{ day: "mon", total: 9 }],
      meta: { total: 1 },
    });
  });

  it("asks the proxy for the dashboard the widget sits on", async () => {
    apiGet.mockImplementation((url: string) =>
      Promise.resolve({
        data: catalogUrl(url) ? CATALOG : { rows: [], fetched_at: "", cached: false },
      })
    );

    mount({ dashboardId: 11 });

    await waitFor(() => expect(apiGet.mock.calls.some(([url]) => dataUrl(url))).toBe(true));
    const [url, config] = apiGet.mock.calls.find(([u]) => dataUrl(u)) as [
      string,
      { params: Record<string, unknown> },
    ];
    expect(url).toBe("/g/2/apps/3/endpoints/app.acme.shop.orders-summary");
    expect(config.params.dashboard_id).toBe(11);
  });

  it("draws an error tile when the app is not answering", async () => {
    apiGet.mockImplementation((url: string) => {
      if (catalogUrl(url)) return Promise.resolve({ data: CATALOG });
      return Promise.reject(new Error("502"));
    });

    mount({ dashboardId: 11 });

    expect(await screen.findByText(/not responding/i)).toBeInTheDocument();
    // The module is never run: it has nothing to draw, and running it over an
    // empty array would claim "no data" rather than "the app is down".
    expect(renderWidget).not.toHaveBeenCalled();
  });

  it("previews from the manifest's own samples and issues zero requests", async () => {
    apiGet.mockImplementation((url: string) =>
      catalogUrl(url)
        ? Promise.resolve({ data: CATALOG })
        : Promise.reject(new Error("a preview must not fetch data"))
    );

    mount({ sampleData: true });

    await waitFor(() => expect(renderWidget).toHaveBeenCalled());
    const call = renderWidget.mock.calls.at(-1)?.[0];
    expect(call.source).toBe(MODULE);
    expect(call.data).toEqual({ source: "app", rows: [{ day: "mon", total: 4 }] });
    // The catalog is a declaration; the data plane is never touched.
    expect(apiGet.mock.calls.every(([url]) => catalogUrl(url))).toBe(true);
  });

  it("has a localized message for the failure it can produce", () => {
    expect(WidgetErrorCode.APP_UNAVAILABLE).toBe("WIDGET_APP_UNAVAILABLE");
  });

  it("asks for the app to be reconnected when the catalog no longer lists it", async () => {
    // The definition is kept as-is when its app goes away; the tile is the
    // surface that says so. Distinct from both the restricted state (this is
    // not an access outcome) and the unavailable state (the catalog answered).
    apiGet.mockImplementation((url: string) => {
      if (catalogUrl(url)) return Promise.resolve({ data: { items: [] } });
      return Promise.reject(new Error("nothing should be fetched for it"));
    });

    mount({ dashboardId: 11 });

    expect(await screen.findByText(/no longer installed/i)).toBeInTheDocument();
    expect(renderWidget).not.toHaveBeenCalled();
    // Only the catalog was read; the data plane was never asked.
    expect(apiGet.mock.calls.every(([url]) => catalogUrl(url))).toBe(true);
  });

  it("says the app is unavailable when its catalog will not load", async () => {
    // A catalog that failed says nothing about whether the app is installed.
    // Reading it as "not installed" would mark every app widget on the board
    // unconfigured and invite someone to repoint bindings that were never wrong.
    apiGet.mockImplementation(() => Promise.reject(new Error("503")));

    mount({ dashboardId: 11 });

    expect(await screen.findByText(/not responding/i)).toBeInTheDocument();
    expect(screen.queryByText(/not configured/i)).toBeNull();
  });
});
