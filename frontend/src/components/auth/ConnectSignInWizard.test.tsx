/**
 * Four questions, in order, and what each answer turns into.
 *
 * The wizard is the only place a community answers all of connect, rule and
 * requirement in one sitting, so what is worth pinning down is the order the
 * three calls go out in, and the two answers that are allowed to be "nothing":
 * a narrowing nobody needs, and a requirement nobody may set.
 */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

const connect = vi.fn();
const createRule = vi.fn();
const updatePolicy = vi.fn();

const inheritedRow = (overrides: Record<string, unknown> = {}) => ({
  id: null,
  inherited: true,
  provider_id: 11,
  provider_slug: "entra",
  provider_display_name: "Entra",
  provider_icon: null,
  claim: null,
  claim_values: [],
  enabled: true,
  auto_join: false,
  login_ready: true,
  ...overrides,
});

let connections: unknown[] = [];
let available: unknown[] = [];

vi.mock("@/hooks/useGuildAuthPolicy", () => ({
  useConnectableProviders: () => ({ data: available, isLoading: false }),
  useGuildProviderConnections: () => ({ data: connections, isLoading: false }),
  useConnectProvider: () => ({ mutateAsync: connect, isPending: false }),
  useCreateClaimRule: () => ({ mutateAsync: createRule, isPending: false }),
  useUpdateGuildAuthPolicy: () => ({ mutateAsync: updatePolicy, isPending: false }),
}));

import { ConnectSignInWizard } from "./ConnectSignInWizard";

const render = (canRequire = true) =>
  renderWithProviders(
    <ConnectSignInWizard guildId={1} open onOpenChange={vi.fn()} canRequire={canRequire} />,
    { auth: { user: buildUser() } }
  );

describe("ConnectSignInWizard", () => {
  beforeEach(() => {
    connections = [];
    available = [
      { id: 11, display_name: "Entra", icon: null, login_ready: true },
      { id: 12, display_name: "Keycloak", icon: null, login_ready: false },
    ];
    connect.mockReset().mockResolvedValue({});
    createRule.mockReset().mockResolvedValue({});
    updatePolicy.mockReset().mockResolvedValue({});
  });

  it("walks the four steps and connects the provider that was chosen", async () => {
    const user = userEvent.setup();
    render();

    expect(screen.getByText("Which way in")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /entra/i }));

    expect(await screen.findByText("Whose people")).toBeInTheDocument();
    await user.click(screen.getByRole("combobox", { name: /whose accounts count as yours/i }));
    await user.click(await screen.findByRole("option", { name: /microsoft entra tenant/i }));
    await user.type(screen.getByLabelText(/values that count/i), "acme-tenant");
    await user.click(screen.getByRole("button", { name: /^next$/i }));

    expect(await screen.findByText("Where they land")).toBeInTheDocument();
    await user.click(screen.getByRole("switch"));
    await user.type(screen.getByLabelText(/a first group/i), "eng-platform");
    await user.click(screen.getByRole("button", { name: /^next$/i }));

    expect(await screen.findByText("Do we insist")).toBeInTheDocument();
    await user.click(screen.getByRole("switch"));
    await user.click(screen.getByRole("button", { name: /connect provider/i }));

    expect(connect).toHaveBeenCalledWith({
      provider_id: 11,
      claim: "tid",
      claim_values: ["acme-tenant"],
      auto_join: true,
      enabled: true,
    });
    expect(createRule).toHaveBeenCalledWith({
      provider_id: 11,
      claim_value: "eng-platform",
      guild_role: "member",
    });
    expect(updatePolicy).toHaveBeenCalledWith({
      policy: "required",
      provider_id: 11,
      require_methods: [],
    });
  });

  it("sends no narrowing at all when the step is skipped", async () => {
    const user = userEvent.setup();
    render();

    await user.click(screen.getByRole("button", { name: /entra/i }));
    await user.click(await screen.findByRole("button", { name: /skip this/i }));
    await user.click(await screen.findByRole("button", { name: /^next$/i }));
    await user.click(await screen.findByRole("button", { name: /connect provider/i }));

    expect(connect).toHaveBeenCalledWith({
      provider_id: 11,
      claim: null,
      claim_values: null,
      auto_join: false,
      enabled: true,
    });
    // Nothing was typed in the optional rule, so no rule was written.
    expect(createRule).not.toHaveBeenCalled();
  });

  it("will not go on from half a narrowing", async () => {
    const user = userEvent.setup();
    render();

    await user.click(screen.getByRole("button", { name: /entra/i }));
    await user.type(await screen.findByLabelText(/values that count/i), "acme-tenant");

    expect(screen.getByRole("button", { name: /^next$/i })).toBeDisabled();
  });

  it("asks three questions of somebody who may not set the requirement", async () => {
    const user = userEvent.setup();
    render(false);

    await user.click(screen.getByRole("button", { name: /entra/i }));
    await user.click(await screen.findByRole("button", { name: /skip this/i }));

    expect(await screen.findByText("Where they land")).toBeInTheDocument();
    expect(screen.getByText("Step 3 of 3")).toBeInTheDocument();
    // The last step finishes rather than leading anywhere.
    await user.click(screen.getByRole("button", { name: /connect provider/i }));

    expect(connect).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Do we insist")).not.toBeInTheDocument();
    expect(updatePolicy).not.toHaveBeenCalled();
  });

  it("starts the narrowing from what the deployment already answered", async () => {
    const user = userEvent.setup();
    connections = [inheritedRow({ claim: "tid", claim_values: ["acme-tenant"] })];
    render();

    expect(screen.getByText("From the deployment")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /entra/i }));

    expect(await screen.findByText("Microsoft Entra tenant")).toBeInTheDocument();
    expect(screen.getByDisplayValue("acme-tenant")).toBeInTheDocument();
  });

  it("offers no provider the deployment cannot sign anybody in with", () => {
    render();

    expect(screen.getByRole("button", { name: /keycloak/i })).toBeDisabled();
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
  });
});
