import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

const createRule = vi.fn();
const deleteRule = vi.fn();

const connection = (providerId: number, name: string) => ({
  id: providerId,
  provider_id: providerId,
  provider_slug: name.toLowerCase(),
  provider_display_name: name,
  provider_icon: null,
  claim: null,
  claim_values: [],
  enabled: true,
  auto_join: false,
  login_ready: true,
});

let rules: unknown[] = [];
let reportingIds: number[] = [];
let connections = [connection(11, "Entra")];

vi.mock("@/hooks/useGuildAuthPolicy", () => ({
  useGuildClaimRules: () => ({
    data: { rules, reporting_provider_ids: reportingIds },
    isLoading: false,
  }),
  useGuildProviderConnections: () => ({ data: connections, isLoading: false }),
  useCreateClaimRule: () => ({ mutate: createRule, isPending: false }),
  useDeleteClaimRule: () => ({ mutate: deleteRule, isPending: false }),
  useUpdateClaimRule: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock("@/hooks/useInitiatives", () => ({
  useInitiativesForGuild: () => ({ data: [{ id: 7, name: "Platform" }], isLoading: false }),
}));

vi.mock("@/hooks/useInitiativeRoles", () => ({
  useInitiativeRoles: (initiativeId: number | null) => ({
    data: initiativeId ? [{ id: 70, display_name: "Contributor" }] : [],
  }),
}));

import { GuildClaimRulesSection } from "./GuildClaimRulesSection";

const render = () =>
  renderWithProviders(<GuildClaimRulesSection guildId={1} />, {
    auth: { user: buildUser() },
  });

describe("GuildClaimRulesSection", () => {
  beforeEach(() => {
    rules = [];
    reportingIds = [11];
    connections = [connection(11, "Entra")];
    createRule.mockReset();
    deleteRule.mockReset();
  });

  it("sends a group and where it lands", async () => {
    const user = userEvent.setup();
    render();

    await user.click(screen.getByRole("button", { name: /add a rule/i }));
    await user.click(await screen.findByLabelText(/^provider$/i));
    await user.click(await screen.findByRole("option", { name: "Entra" }));
    await user.type(screen.getByLabelText(/^group$/i), "eng-platform");
    await user.click(screen.getAllByRole("button", { name: /add a rule/i }).at(-1)!);

    await waitFor(() => expect(createRule).toHaveBeenCalled());
    expect(createRule.mock.calls[0][0]).toMatchObject({
      provider_id: 11,
      claim_value: "eng-platform",
      guild_role: "member",
      initiative_id: null,
      initiative_role_id: null,
    });
  });

  it("asks for a role once an initiative is named", async () => {
    const user = userEvent.setup();
    render();

    await user.click(screen.getByRole("button", { name: /add a rule/i }));
    expect(screen.queryByLabelText(/in that initiative/i)).not.toBeInTheDocument();

    await user.click(screen.getByLabelText(/and start in/i));
    await user.click(await screen.findByRole("option", { name: "Platform" }));

    expect(await screen.findByLabelText(/in that initiative/i)).toBeInTheDocument();
  });

  it("says when a provider reports no groups, rather than hiding it", async () => {
    reportingIds = [];
    rules = [
      {
        id: 3,
        provider_id: 11,
        provider_display_name: "Entra",
        provider_icon: null,
        claim_value: "eng-platform",
        guild_role: "member",
        initiative_id: null,
        initiative_name: null,
        initiative_role_id: null,
        initiative_role_name: null,
      },
    ];
    render();

    expect(screen.getByText("eng-platform")).toBeInTheDocument();
    expect(screen.getByText(/no groups reported/i)).toBeInTheDocument();
  });

  it("points at the connection when there is nothing to write a rule against", () => {
    connections = [];
    render();

    expect(screen.getByText(/connect a provider first/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add a rule/i })).toBeDisabled();
  });
});
