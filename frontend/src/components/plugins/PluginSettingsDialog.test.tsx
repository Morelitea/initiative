/**
 * The community's own credential is the seat's to fill in: a superadmin gets
 * its form, and an admin below the seat is told whether it is set.
 */
import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { buildCommunity } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { CommunityPluginDetail } from "@/api/generated/initiativeAPI.schemas";

import { PluginSettingsDialog } from "./PluginSettingsDialog";

const detail = {
  id: 3,
  name: "Shop",
  definition: {},
  requested_scopes: [],
  consents: [],
  connections: [
    {
      id: "admin",
      scope: "static",
      label: { en: "Admin API" },
      fields: [{ key: "shop_domain", type: "string", label: { en: "Shop domain" } }],
      access_hint: null,
      values: {},
      has_value: { shop_domain: true },
      satisfied: true,
      runs_flow: false,
      status: null,
      account_label: null,
      blocked: false,
    },
  ],
} as unknown as CommunityPluginDetail;

vi.mock("@/hooks/useCommunityPluginDetail", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useCommunityPluginDetail")>()),
  useCommunityPluginDetail: () => ({ data: detail, isLoading: false }),
}));

vi.mock("./PluginMembersPanel", () => ({ PluginMembersPanel: () => null }));

const renderAs = (role: "superadmin" | "admin") => {
  const community = buildCommunity({ role });
  renderWithProviders(
    <PluginSettingsDialog pluginId={3} isCommunityAdmin open onOpenChange={() => {}} />,
    {
      communities: {
        communities: [community],
        activeCommunityId: community.id,
        activeCommunity: community,
      },
    }
  );
};

describe("PluginSettingsDialog", () => {
  it("gives the seat the community credential's form", async () => {
    renderAs("superadmin");
    expect(await screen.findByLabelText("Shop domain")).toBeInTheDocument();
  });

  it("tells an admin below the seat whether it is set", async () => {
    renderAs("admin");
    expect(await screen.findByText(/community admin has set this up/i)).toBeInTheDocument();
    expect(screen.queryByLabelText("Shop domain")).not.toBeInTheDocument();
  });
});
