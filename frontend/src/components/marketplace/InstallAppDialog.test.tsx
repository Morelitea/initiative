/**
 * The install dialog is the seat's consent, sent with the install.
 *
 * What matters is what reaches the server: every scope the server allows is
 * granted unless the seat unticks it, a scope it does not allow can never be
 * sent, placement is asked of an app with a page inside initiatives or access
 * to reach there, and moderators open a page unless the seat says otherwise.
 */

import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildMarketplaceListingDetail } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import type {
  GuildAppInstall,
  MarketplaceListingDetail,
} from "@/api/generated/initiativeAPI.schemas";

import { InstallAppDialog } from "./InstallAppDialog";

const sent: GuildAppInstall[] = [];

vi.mock("@/hooks/useGuildApps", () => ({
  useInstallGuildApp: () => ({
    isPending: false,
    mutate: (body: GuildAppInstall) => sent.push(body),
  }),
}));

vi.mock("@/hooks/useInitiatives", () => ({
  useInitiatives: () => ({
    isLoading: false,
    data: [
      { id: 11, name: "Garden" },
      { id: 12, name: "Kitchen" },
    ],
  }),
}));

const listing = (overrides: Partial<MarketplaceListingDetail> = {}) =>
  buildMarketplaceListingDetail({
    uid: "WIDGETCO000001",
    kind: "app",
    name: "WidgetCo",
    requested_scopes: ["projects:read", "projects:write", "members:read"],
    grantable_scopes: ["projects:read", "members:read"],
    has_initiative_surfaces: true,
    ...overrides,
  });

const open = (overrides: Partial<MarketplaceListingDetail> = {}) =>
  renderPage(() => (
    <InstallAppDialog listing={listing(overrides)} open onOpenChange={() => undefined} />
  ));

const install = async () => {
  (await screen.findByRole("button", { name: "Add to community" })).click();
  await waitFor(() => expect(sent).toHaveLength(1));
  return sent[0];
};

beforeEach(() => {
  sent.length = 0;
});

describe("InstallAppDialog", () => {
  it("grants everything the server allows, everywhere, to moderators by default", async () => {
    open();

    expect(await screen.findByLabelText("Read projects")).toBeChecked();
    expect(screen.getByLabelText("See who is in your community")).toBeChecked();

    expect(await install()).toEqual({
      listing_uid: "WIDGETCO000001",
      name: "WidgetCo",
      granted_scopes: ["projects:read", "members:read"],
      placements: "all",
      role_kinds: ["moderator"],
    });
  });

  it("shows a scope the server does not allow, and cannot tick it", async () => {
    open();

    const change = await screen.findByLabelText("Read and change projects");
    expect(change).toBeDisabled();
    expect(change).not.toBeChecked();
    expect(screen.getByText("This server doesn't allow it")).toBeInTheDocument();
  });

  it("sends what the seat unticked as not granted", async () => {
    open();

    (await screen.findByLabelText("See who is in your community")).click();
    await waitFor(() =>
      expect(screen.getByLabelText("See who is in your community")).not.toBeChecked()
    );

    expect((await install()).granted_scopes).toEqual(["projects:read"]);
  });

  it("places it in the initiatives picked, for the roles chosen", async () => {
    open();

    (await screen.findByLabelText("Only the initiatives I choose")).click();
    (await screen.findByLabelText("Kitchen")).click();
    (await screen.findByLabelText("Project managers")).click();
    await waitFor(() => expect(screen.getByLabelText("Kitchen")).toBeChecked());

    const body = await install();
    expect(body.placements).toEqual([12]);
    expect(body.role_kinds).toEqual(["moderator", "project_manager"]);
  });

  it("places an app with access but no page, and asks nothing about roles", async () => {
    open({ has_initiative_surfaces: false });

    expect(await screen.findByText("Where it works")).toBeInTheDocument();
    expect(
      screen.getByText("It reads and changes things only in the initiatives you choose.")
    ).toBeInTheDocument();
    expect(screen.queryByText("Who can open it there")).not.toBeInTheDocument();

    const body = await install();
    expect(body.placements).toEqual("all");
    expect(body.role_kinds).toEqual([]);
  });

  it("asks to use another app by that app's name, and grants it", async () => {
    open({
      requested_scopes: ["projects:read", "apps:acme.github"],
      grantable_scopes: ["projects:read", "apps:acme.github"],
      app_names: { "acme.github": "GitHub" },
    });

    expect(await screen.findByLabelText("Use GitHub in this community")).toBeChecked();
    expect((await install()).granted_scopes).toEqual(["projects:read", "apps:acme.github"]);
  });

  it("says an app with no name by its public id", async () => {
    open({ requested_scopes: ["apps:acme.github"], grantable_scopes: [] });

    const use = await screen.findByLabelText("Use acme.github in this community");
    expect(use).toBeDisabled();
  });

  it("asks nothing about placement for an app with no page and no access", async () => {
    open({ has_initiative_surfaces: false, requested_scopes: [], grantable_scopes: [] });

    await screen.findByRole("button", { name: "Add to community" });
    expect(screen.queryByText("Where it works")).not.toBeInTheDocument();
    expect(screen.queryByText("Who can open it there")).not.toBeInTheDocument();
    expect((await install()).placements).toEqual([]);
  });
});
