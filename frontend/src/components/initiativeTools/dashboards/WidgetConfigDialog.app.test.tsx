/**
 * Configuring an installed app's widget — the three things that were missing.
 *
 * **The source list was empty.** An app widget's type is namespaced
 * `app:<uid>:<widget>`, and this dialog looked it up in the built-in widget
 * catalog, which only ever holds this build's own primitives. The lookup missed,
 * `sources` fell back to `[]`, and every app widget on every canvas offered a
 * data-source control with nothing in it.
 *
 * **A parameter with a menu behind it was a text box.** A manifest can say
 * `options_from` — "the values this permits are what that read of mine answers"
 * — and nothing on this side read it, so a repository, a label or a board was
 * typed from memory on a form that could have offered the list.
 *
 * **A menu that will not resolve must leave the field typeable.** A source can
 * fail for reasons that say nothing about the value: the app is down, a
 * credential is unconnected, a sibling has not been chosen yet. A control
 * disabled on any of those makes a configuration that would have worked
 * unreachable, so the fallback is an input rather than a dead select.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import type { DefinitionWidget } from "@/lib/widgets/definition";

const apiGet = vi.hoisted(() => vi.fn());
vi.mock("@/api/client", () => ({
  apiClient: { get: apiGet, post: vi.fn(), put: vi.fn(), delete: vi.fn() },
  API_BASE_URL: "http://test/api/v1",
}));

const renderWidget = vi.hoisted(() => vi.fn());
const readWidgetMeta = vi.hoisted(() => vi.fn());
vi.mock("@/lib/widgets/runtime/host", () => ({ renderWidget, readWidgetMeta }));

import { WidgetConfigDialog } from "./WidgetConfigDialog";

const APP_UID = "SHOPAPP0000001";
const WIDGET_TYPE = `app:${APP_UID}:summary`;
const ORDERS = "app.acme.shop.orders-summary";
const REVENUE = "app.acme.shop.revenue";

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
          module_source: "export const render = () => ({});",
          endpoints: [ORDERS, REVENUE],
          sample_data: {},
        },
      ],
      endpoints: [
        {
          id: ORDERS,
          visibility: "member",
          cache_ttl_seconds: 60,
          params: [
            {
              key: "shop",
              type: "string",
              label: { en: "Shop" },
              required: true,
              options_from: { endpoint: "app.acme.shop.list-shops", key: "names" },
            },
            { key: "limit", type: "int", label: { en: "Limit" } },
          ],
        },
        { id: REVENUE, visibility: "member", cache_ttl_seconds: 0, params: [] },
      ],
    },
  ],
};

const widget: DefinitionWidget = {
  id: "w1",
  type: WIDGET_TYPE,
  grid: { x: 0, y: 0, w: 6, h: 4 },
  binding: { source: "app", app_uid: APP_UID, endpoint_id: ORDERS },
};

const isCatalog = (url: string) => url.endsWith("/apps/widget-catalog");
const isOptions = (url: string) => url.includes("/options");

/** The app answers a menu, or says it cannot. */
const serve = (options: { menu?: unknown[]; unavailable?: string | null } = {}) =>
  apiGet.mockImplementation((url: string) => {
    if (isCatalog(url)) return Promise.resolve({ data: CATALOG });
    if (isOptions(url)) {
      return Promise.resolve({
        data: { options: options.menu ?? [], unavailable: options.unavailable ?? null },
      });
    }
    return Promise.resolve({ data: {} });
  });

const onSave = vi.fn();

beforeEach(() => {
  apiGet.mockReset();
  onSave.mockReset();
  renderWidget.mockReset();
  readWidgetMeta.mockReset();
  renderWidget.mockResolvedValue({ ok: true, spec: { scene: { kind: "empty" } } });
  readWidgetMeta.mockResolvedValue({ name: { en: "Summary" } });
});

const mount = () =>
  renderWithProviders(
    <WidgetConfigDialog
      widget={widget}
      catalog={{ widgets: [], presets: [] }}
      initiativeId={7}
      open
      onOpenChange={() => {}}
      onSave={onSave}
    />,
    { guilds: { activeGuildId: 2 } }
  );

describe("configuring an app widget", () => {
  it("offers a data source, which the built-in catalog does not know about", async () => {
    // The bug, at its narrowest: the built-in catalog passed in here is empty,
    // exactly as it is for any `app:` type, and the control still has an option.
    serve();
    mount();

    const source = await screen.findByRole("combobox", { name: /data source/i });
    expect(within(source).getByText("App data")).toBeInTheDocument();
  });

  it("offers the reads the widget declares, and no others", async () => {
    serve();
    const user = userEvent.setup();
    mount();

    await user.click(await screen.findByRole("combobox", { name: /what it reads/i }));
    expect(await screen.findByRole("option", { name: ORDERS })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: REVENUE })).toBeInTheDocument();
  });

  it("draws a menu for a parameter whose app said where its values come from", async () => {
    serve({
      menu: [
        { value: "north", label: null },
        { value: "south", label: null },
      ],
    });
    const user = userEvent.setup();
    mount();

    await user.click(await screen.findByRole("combobox", { name: /shop/i }));
    expect(await screen.findByRole("option", { name: "north" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "south" })).toBeInTheDocument();

    // And it asked the app, for that parameter, rather than guessing.
    const asked = apiGet.mock.calls.find(([url]) => isOptions(url));
    expect(asked?.[0]).toContain(encodeURIComponent(ORDERS));
    expect(asked?.[1]?.params?.param).toBe("shop");
  });

  it("saves the chosen value onto the binding's own params", async () => {
    serve({ menu: [{ value: "north", label: null }] });
    const user = userEvent.setup();
    mount();

    await user.click(await screen.findByRole("combobox", { name: /shop/i }));
    await user.click(await screen.findByRole("option", { name: "north" }));
    await user.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(onSave.mock.calls[0][0].binding.params).toEqual({ shop: "north" });
  });

  it("leaves the field typeable when the app will not answer", async () => {
    // The rule that keeps a form usable through an outage. Not a disabled
    // select and not an empty one: something somebody can type into.
    serve({ unavailable: "unresolved" });
    const user = userEvent.setup();
    mount();

    const field = await screen.findByLabelText(/shop/i);
    await user.type(field, "north");
    await user.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(onSave.mock.calls[0][0].binding.params).toEqual({ shop: "north" });
  });

  it("still types a parameter that never named a source", async () => {
    serve();
    const user = userEvent.setup();
    mount();

    await user.type(await screen.findByLabelText(/limit/i), "5");
    await user.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(onSave.mock.calls[0][0].binding.params).toEqual({ limit: 5 });
  });

  it("drops the old read's answers when it is pointed at a different one", async () => {
    // They were that endpoint's parameters. Carrying them onto another one is
    // how a binding ends up holding a value the endpoint never declared.
    serve({ menu: [{ value: "north", label: null }] });
    const user = userEvent.setup();
    mount();

    await user.click(await screen.findByRole("combobox", { name: /shop/i }));
    await user.click(await screen.findByRole("option", { name: "north" }));

    await user.click(screen.getByRole("combobox", { name: /what it reads/i }));
    await user.click(await screen.findByRole("option", { name: REVENUE }));
    await user.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(onSave.mock.calls[0][0].binding.endpoint_id).toBe(REVENUE);
    expect(onSave.mock.calls[0][0].binding.params).toBeUndefined();
  });
});
