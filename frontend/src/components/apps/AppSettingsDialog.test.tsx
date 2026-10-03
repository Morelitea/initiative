/**
 * The community's own credential is the seat's to fill in: a superadmin gets
 * its form, and an admin below the seat is told whether it is set.
 */
import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { buildCommunity } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { CommunityAppDetail } from "@/api/generated/initiativeAPI.schemas";

import { AppSettingsDialog } from "./AppSettingsDialog";

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
} as unknown as CommunityAppDetail;

vi.mock("@/hooks/useCommunityAppDetail", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useCommunityAppDetail")>()),
  useCommunityAppDetail: () => ({ data: detail, isLoading: false }),
}));

vi.mock("./AppMembersPanel", () => ({ AppMembersPanel: () => null }));

const renderAs = (role: "superadmin" | "admin") => {
  const community = buildCommunity({ role });
  renderWithProviders(
    <AppSettingsDialog appId={3} isCommunityAdmin open onOpenChange={() => {}} />,
    {
      communities: {
        communities: [community],
        activeCommunityId: community.id,
        activeCommunity: community,
      },
    }
  );
};

describe("AppSettingsDialog", () => {
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
