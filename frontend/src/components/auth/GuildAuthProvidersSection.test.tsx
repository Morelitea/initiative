/**
 * What a community does with an arrangement it did not make.
 *
 * An inherited row is the deployment's answer for a provider this community
 * has said nothing about. It has no row of its own to switch or disconnect —
 * what it has is the offer to take the arrangement over, which writes a
 * connection that shadows the default from then on.
 */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

const connect = vi.fn();
const updateConnection = vi.fn();

const row = (overrides: Record<string, unknown> = {}) => ({
  id: 1,
  provider_id: 11,
  provider_slug: "entra",
  provider_display_name: "Entra",
  provider_icon: null,
  claim: null,
  claim_values: [],
  enabled: true,
  auto_join: false,
  login_ready: true,
  inherited: false,
  ...overrides,
});

let connections: unknown[] = [];

vi.mock("@/hooks/useGuildAuthPolicy", () => ({
  useGuildProviderConnections: () => ({ data: connections, isLoading: false }),
  useConnectableProviders: () => ({
    data: [{ id: 11, display_name: "Entra", icon: null, login_ready: true }],
    isLoading: false,
  }),
  useConnectProvider: () => ({ mutate: connect, isPending: false }),
  useUpdateProviderConnection: () => ({ mutate: updateConnection, isPending: false }),
  useDisconnectProvider: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { GuildAuthProvidersSection } from "./GuildAuthProvidersSection";

const onConnect = vi.fn();

const render = () =>
  renderWithProviders(<GuildAuthProvidersSection guildId={1} onConnect={onConnect} />, {
    auth: { user: buildUser() },
  });

describe("GuildAuthProvidersSection", () => {
  beforeEach(() => {
    connections = [];
    connect.mockReset();
    updateConnection.mockReset();
  });

  it("marks an inherited arrangement as the deployment's", () => {
    connections = [row({ id: null, inherited: true, claim: "tid", claim_values: ["acme-tenant"] })];
    render();

    expect(screen.getByText(/from the deployment/i)).toBeInTheDocument();
    expect(screen.getByText(/only accounts whose tid is acme-tenant/i)).toBeInTheDocument();
  });

  it("offers to take an inherited arrangement over, rather than to switch it off", () => {
    connections = [row({ id: null, inherited: true })];
    render();

    expect(screen.getByRole("button", { name: /make it ours/i })).toBeInTheDocument();
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  });

  it("opens the wizard on the provider it is taking over", async () => {
    const user = userEvent.setup();
    connections = [row({ id: null, inherited: true, claim: "tid", claim_values: ["acme-tenant"] })];
    render();

    await user.click(screen.getByRole("button", { name: /make it ours/i }));

    // One flow, not two: this card used to carry its own shorter copy of the
    // wizard's first steps. It now asks for the wizard, opened on the
    // provider being taken over, and the wizard seeds itself from what the
    // deployment answered.
    expect(onConnect).toHaveBeenCalledWith(connections[0].provider_id);
  });

  it("switches and disconnects a connection the community made itself", () => {
    connections = [row({ id: 5, inherited: false })];
    render();

    expect(screen.getByRole("switch")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /make it ours/i })).not.toBeInTheDocument();
  });

  it("still offers a provider it only inherits in the picker", () => {
    connections = [row({ id: null, inherited: true })];
    render();

    // Taking an inherited arrangement over is a connect, so the provider has
    // to stay choosable — only what the community said itself is filtered out.
    expect(screen.getByRole("button", { name: /connect a provider/i })).toBeEnabled();
  });
});
