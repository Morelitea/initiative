import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

// What the server says about this community and this member. Flipped per test.
let guildRole = "superadmin";
let grantSettingsLevel: "admin" | "superadmin" | null = null;
let guildId = 4;
let authOptions: string[] | null = ["restrictions", "providers", "require_sign_in"];
let allowApiKeys: boolean | null = true;
let sessionLimit: boolean | null = false;
let grantedAuthSettings = {
  auth_options: ["restrictions", "providers", "require_sign_in"],
  allow_api_keys: true,
  enforce_compliance_session: false,
};
let policy: {
  policy: "open" | "required";
  provider_id: number | null;
  provider_slug: string | null;
  provider_display_name: string | null;
  require_methods: string[];
} = {
  policy: "open",
  provider_id: null,
  provider_slug: null,
  provider_display_name: null,
  require_methods: [],
};

const savePolicy = vi.fn();
const saveApiAccess = vi.fn();
const saveSessionLimit = vi.fn();
const refreshGuilds = vi.fn(() => Promise.resolve());

// Partial: the render helper reaches for ``GuildContext`` from this module.
vi.mock(import("@/hooks/useGuilds"), async (importOriginal) => ({
  ...(await importOriginal()),
  useGuilds: () => ({
    activeGuild: {
      id: guildId,
      name: "Test Community",
      role: guildRole,
      grantSettingsLevel,
      auth_options: authOptions,
      allow_api_keys: allowApiKeys,
      enforce_compliance_session: sessionLimit,
    },
    refreshGuilds,
  }),
}));

vi.mock("@/hooks/useActiveGuildId", () => ({ useActiveGuildId: () => guildId }));

// ``useServer`` is left real: the render helper provides its context, and
// mocking the module would take ``ServerContext`` with it.

vi.mock("@/hooks/useGuildAuthPolicy", () => ({
  useGuildAuthPolicy: () => ({ data: policy, isLoading: false }),
  useGuildAuthSettings: () => ({ data: grantedAuthSettings, refetch: vi.fn() }),
  useUpdateGuildAuthPolicy: () => ({ mutate: savePolicy, isPending: false }),
  useUpdateGuildApiAccess: () => ({ mutate: saveApiAccess, isPending: false }),
  useUpdateGuildSessionLimit: () => ({ mutate: saveSessionLimit, isPending: false }),
  useGuildProviderConnections: () => ({
    data: [
      {
        id: 1,
        provider_id: 11,
        provider_slug: "corp",
        provider_display_name: "Corp SSO",
        provider_icon: null,
        claim: null,
        claim_values: [],
        enabled: true,
        login_ready: true,
      },
      {
        id: 2,
        provider_id: 12,
        provider_slug: "contractors",
        provider_display_name: "Contractors",
        provider_icon: null,
        claim: null,
        claim_values: [],
        enabled: true,
        login_ready: true,
      },
    ],
    isLoading: false,
  }),
  useConnectableProviders: () => ({ data: [], isLoading: false }),
  useGuildLoginProviders: () => ({ data: { providers: [] } }),
  useConnectProvider: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateProviderConnection: () => ({ mutate: vi.fn(), isPending: false }),
  useDisconnectProvider: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { SettingsGuildAuthPage } from "./SettingsGuildAuthPage";

const render = () =>
  renderWithProviders(<SettingsGuildAuthPage />, { auth: { user: buildUser() } });

const requirementRadio = () => screen.getByLabelText(/require single sign-on/i);

/** The provider picker lists the same names the registry below does, so
 * choose from the open listbox rather than from the page. */
const chooseOption = async (user: ReturnType<typeof userEvent.setup>, name: string | RegExp) => {
  await user.click(await screen.findByRole("combobox"));
  await user.click(await screen.findByRole("option", { name }));
};

describe("SettingsGuildAuthPage", () => {
  beforeEach(() => {
    savePolicy.mockClear();
    saveApiAccess.mockClear();
    saveSessionLimit.mockClear();
    refreshGuilds.mockClear();
    guildRole = "superadmin";
    grantSettingsLevel = null;
    guildId = 4;
    authOptions = ["restrictions", "providers", "require_sign_in"];
    allowApiKeys = true;
    sessionLimit = false;
    grantedAuthSettings = {
      auth_options: ["restrictions", "providers", "require_sign_in"],
      allow_api_keys: true,
      enforce_compliance_session: false,
    };
    policy = {
      policy: "open",
      provider_id: null,
      provider_slug: null,
      provider_display_name: null,
      require_methods: [],
    };
  });

  describe("choosing what the community requires", () => {
    it("saves 'any of ours' as a rule that names no provider", async () => {
      const user = userEvent.setup();
      render();

      await user.click(requirementRadio());
      await chooseOption(user, "Any of our sign-in providers");
      await user.click(screen.getByRole("button", { name: /save/i }));

      expect(savePolicy).toHaveBeenCalledTimes(1);
      expect(savePolicy.mock.calls[0][0]).toEqual({
        policy: "required",
        require_methods: ["sso"],
      });
    });

    it("saves a named provider as a rule that names no method", async () => {
      const user = userEvent.setup();
      render();

      await user.click(requirementRadio());
      await chooseOption(user, "Contractors");
      await user.click(screen.getByRole("button", { name: /save/i }));

      // Sent rather than omitted: switching to a named provider is also how a
      // method requirement is cleared, so the empty list is the instruction.
      expect(savePolicy.mock.calls[0][0]).toEqual({
        policy: "required",
        provider_id: 12,
        require_methods: [],
      });
    });

    it("switches back from 'any of ours' to a named provider", async () => {
      policy = {
        policy: "required",
        provider_id: null,
        provider_slug: null,
        provider_display_name: null,
        require_methods: ["sso"],
      };
      const user = userEvent.setup();
      render();

      await chooseOption(user, "Corp SSO");
      await user.click(screen.getByRole("button", { name: /save/i }));

      expect(savePolicy.mock.calls[0][0]).toEqual({
        policy: "required",
        provider_id: 11,
        require_methods: [],
      });
    });

    it("has nothing to save until something changes", async () => {
      policy = {
        policy: "required",
        provider_id: null,
        provider_slug: null,
        provider_display_name: null,
        require_methods: ["sso"],
      };
      render();

      expect(screen.getByRole("button", { name: /save/i })).toBeDisabled();
    });
  });

  describe("who may reach it", () => {
    it.each(["admin", "member"])("shows %s nothing at all", (role) => {
      // The whole page is the seat's, so there is nothing here to render
      // read-only. The tab is hidden the same way; this is the direct-URL half.
      guildRole = role;
      const { container } = render();

      expect(container).toBeEmptyDOMElement();
    });

    it("leaves the superadmin's own controls alone", () => {
      render();
      expect(requirementRadio()).not.toBeDisabled();
    });

    it("gives a superadmin settings grantee the current controls", () => {
      guildRole = "member";
      grantSettingsLevel = "superadmin";
      authOptions = null;
      allowApiKeys = null;
      sessionLimit = null;
      grantedAuthSettings = {
        auth_options: ["restrictions", "providers", "require_sign_in"],
        allow_api_keys: false,
        enforce_compliance_session: true,
      };

      render();

      expect(requirementRadio()).toBeInTheDocument();
      expect(screen.getByLabelText(/allow personal api keys/i)).not.toBeChecked();
      expect(screen.getByLabelText(/twelve-hour session limit/i)).toBeChecked();
    });
  });

  describe("asking for a second factor", () => {
    it("asks for it alongside a named provider", async () => {
      const user = userEvent.setup();
      render();

      await user.click(requirementRadio());
      await chooseOption(user, "Contractors");
      await user.click(screen.getByLabelText(/second factor/i));
      await user.click(screen.getByRole("button", { name: /save/i }));

      expect(savePolicy.mock.calls[0][0]).toEqual({
        policy: "required",
        provider_id: 12,
        require_methods: ["totp"],
      });
    });

    it("reads a factor-only rule as one, not as 'any of ours'", async () => {
      // require_methods is no longer a yes/no: a rule can name the factor and
      // no provider, which is not the same as asking for the community's own
      // single sign-on.
      policy = {
        policy: "required",
        provider_id: null,
        provider_slug: null,
        provider_display_name: null,
        require_methods: ["totp"],
      };
      render();

      expect(await screen.findByLabelText(/second factor/i)).toBeChecked();
      expect(screen.getByRole("button", { name: /save/i })).toBeDisabled();
    });
  });

  describe("declining personal API keys", () => {
    const apiSwitch = () => screen.getByLabelText(/allow personal api keys/i);

    it("saves as it is switched, with no button to press", async () => {
      const user = userEvent.setup();
      render();

      expect(apiSwitch()).toBeChecked();
      await user.click(apiSwitch());

      expect(saveApiAccess).toHaveBeenCalledTimes(1);
      expect(saveApiAccess.mock.calls[0][0]).toEqual({ allow_api_keys: false });
    });

    it("shows what a community that declines them has chosen", () => {
      allowApiKeys = false;
      render();

      expect(apiSwitch()).not.toBeChecked();
      expect(screen.getByText(/no key can be created for this community/i)).toBeInTheDocument();
    });

    it("is not on offer to an ordinary admin, like the rest of the page", () => {
      guildRole = "admin";
      render();

      expect(screen.queryByLabelText(/allow personal api keys/i)).not.toBeInTheDocument();
    });

    it("goes with the rest of the page where the master option is not held", () => {
      // A community that configures no part of its own sign-in is not asked
      // about API keys either.
      authOptions = [];
      render();

      expect(screen.queryByLabelText(/allow personal api keys/i)).not.toBeInTheDocument();
      expect(screen.queryByLabelText(/require single sign-on/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/member sign-in link/i)).not.toBeInTheDocument();
    });

    it("stays on offer to a community granted the master and nothing else", () => {
      // The two beneath it are separate grants; this one is not.
      authOptions = ["restrictions"];
      render();

      expect(apiSwitch()).toBeInTheDocument();
      expect(screen.queryByLabelText(/require single sign-on/i)).not.toBeInTheDocument();
    });
  });

  describe("how often members sign in again", () => {
    const limitSwitch = () => screen.getByLabelText(/twelve-hour session limit/i);

    it("saves as it is switched, with no button to press", async () => {
      const user = userEvent.setup();
      render();

      expect(limitSwitch()).not.toBeChecked();
      await user.click(limitSwitch());

      expect(saveSessionLimit).toHaveBeenCalledTimes(1);
      expect(saveSessionLimit.mock.calls[0][0]).toEqual({ enforce_compliance_session: true });
    });

    it("shows what a community held to the standard has chosen", () => {
      sessionLimit = true;
      render();

      expect(limitSwitch()).toBeChecked();
      expect(screen.getByText(/sign in again every twelve hours/i)).toBeInTheDocument();
    });

    it("is the seat's, not an ordinary admin's", () => {
      guildRole = "admin";
      render();

      expect(screen.queryByLabelText(/twelve-hour session limit/i)).not.toBeInTheDocument();
    });

    it("does not carry a pending choice or failure into another community", async () => {
      const user = userEvent.setup();
      const view = render();

      await user.click(limitSwitch());
      const pending = saveSessionLimit.mock.calls[0]?.[1] as {
        onError: (error: unknown) => void;
      };

      guildId = 5;
      sessionLimit = false;
      view.rerender(<SettingsGuildAuthPage />);

      expect(limitSwitch()).not.toBeChecked();

      act(() => pending.onError(new Error("old community failed")));
      expect(screen.queryByText("Could not save the session limit")).not.toBeInTheDocument();
    });
  });
});
