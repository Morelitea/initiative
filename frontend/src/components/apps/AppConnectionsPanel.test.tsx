/**
 * How a guild's own credential is drawn, now that not all of them are typed.
 *
 * The panel has always split connections by who supplies them. The newer split
 * is inside the guild half: some are a form an admin fills in, and some are
 * granted at the vendor — an organization-wide install on the vendor's own
 * page, which no text box can express. A connection with a `connect_path` gets
 * a button instead of inputs, and what came back is shown rather than reduced
 * to "Set", because an admin who just chose an account needs to be able to see
 * which one they chose.
 */
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import type { AppConnection } from "@/api/appConnections";

import { AppConnectionsPanel } from "./AppConnectionsPanel";

const connect = vi.fn();
const save = vi.fn();
const disconnect = vi.fn();

vi.mock("@/hooks/useGuildAppDetail", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useGuildAppDetail")>()),
  useConnectApp: () => ({ mutate: connect, isPending: false }),
  useUpdateAppConfig: () => ({ mutate: save, isPending: false }),
  useDisconnectApp: () => ({ mutate: disconnect, isPending: false }),
}));

const opened = vi.fn();

const base: AppConnection = {
  id: "workspace",
  scope: "static",
  label: { en: "GitHub organization" },
  fields: [],
  values: {},
  has_value: {},
  satisfied: false,
  blocked: false,
};

/** The community's own credential, granted at the vendor rather than typed. */
const vendorFlow: AppConnection = {
  ...base,
  connect_path: "/install/github",
  fields: [{ key: "owner", type: "string", label: { en: "Owner" }, required: true, managed: true }],
};

/** The other kind: a form an admin fills in. */
const typed: AppConnection = {
  ...base,
  id: "admin",
  label: { en: "Admin API" },
  fields: [{ key: "shop_domain", type: "string", label: { en: "Shop domain" }, required: true }],
};

const render = (connection: AppConnection, isGuildAdmin = true) =>
  renderPage(() => (
    <AppConnectionsPanel appId={3} connections={[connection]} isGuildAdmin={isGuildAdmin} />
  ));

beforeEach(() => {
  connect.mockReset();
  save.mockReset();
  disconnect.mockReset();
  opened.mockReset();
  vi.stubGlobal("open", opened);
});

describe("a community credential granted at the vendor", () => {
  it("offers a button rather than a form", async () => {
    render(vendorFlow);

    expect(await screen.findByRole("button", { name: "Connect" })).toBeInTheDocument();
    // Every field is written back by the app, so there is nothing to type and
    // nothing to save.
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
  });

  it("sends the admin to the address the server built", async () => {
    connect.mockImplementation((_id, options) =>
      options.onSuccess({ connect_url: "https://github-app.test/install/github?x=1" })
    );
    render(vendorFlow);

    fireEvent.click(await screen.findByRole("button", { name: "Connect" }));

    await waitFor(() => expect(connect).toHaveBeenCalledWith("workspace", expect.anything()));
    // A new tab, and one that cannot reach back into this page.
    expect(opened).toHaveBeenCalledWith(
      "https://github-app.test/install/github?x=1",
      "_blank",
      "noopener,noreferrer"
    );
  });

  it("shows what the flow recorded, not just that something is set", async () => {
    render({
      ...vendorFlow,
      satisfied: true,
      has_value: { owner: true },
      values: { owner: "morelitea" },
    });

    expect(await screen.findByText("morelitea")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reconnect" })).toBeInTheDocument();
  });

  it("tells a member who cannot manage it what they are waiting on", async () => {
    render(vendorFlow, false);

    expect(
      await screen.findByText(/community admin still has to set this up/i)
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Connect" })).not.toBeInTheDocument();
  });
});

describe("a community credential that is typed", () => {
  it("still draws its form, and no vendor button", async () => {
    render(typed);

    expect(await screen.findByLabelText(/Shop domain/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Connect" })).not.toBeInTheDocument();
  });
});
