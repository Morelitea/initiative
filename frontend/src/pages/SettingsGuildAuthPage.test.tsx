import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

// What the server says about this community and this member. Flipped per test.
let guildRole = "security_admin";
let authOptions: string[] = ["providers", "require_sign_in"];
let allowApiKeys = true;
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
const refreshGuilds = vi.fn(() => Promise.resolve());

// Partial: the render helper reaches for ``GuildContext`` from this module.
vi.mock(import("@/hooks/useGuilds"), async (importOriginal) => ({
  ...(await importOriginal()),
  useGuilds: () => ({
    activeGuild: {
      id: 4,
      name: "Test Community",
      role: guildRole,
      auth_options: authOptions,
      allow_api_keys: allowApiKeys,
    },
    refreshGuilds,
  }),
}));

vi.mock("@/hooks/useActiveGuildId", () => ({ useActiveGuildId: () => 4 }));

// ``useServer`` is left real: the render helper provides its context, and
// mocking the module would take ``ServerContext`` with it.

vi.mock("@/hooks/useGuildAuthPolicy", () => ({
  useGuildAuthPolicy: () => ({ data: policy, isLoading: false }),
  useUpdateGuildAuthPolicy: () => ({ mutate: savePolicy, isPending: false }),
  useUpdateGuildApiAccess: () => ({ mutate: saveApiAccess, isPending: false }),
  useGuildAuthProviders: () => ({
    data: [
      { id: 11, slug: "corp", display_name: "Corp SSO", enabled: true },
      { id: 12, slug: "contractors", display_name: "Contractors", enabled: true },
    ],
    isLoading: false,
  }),
  useGuildLoginProviders: () => ({ data: { providers: [] } }),
  useCreateGuildAuthProvider: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateGuildAuthProvider: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteGuildAuthProvider: () => ({ mutate: vi.fn(), isPending: false }),
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
    refreshGuilds.mockClear();
    guildRole = "security_admin";
    authOptions = ["providers", "require_sign_in"];
    allowApiKeys = true;
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

  describe("who may change it", () => {
    it("lets an ordinary admin read the page and change nothing", async () => {
      guildRole = "admin";
      render();

      expect(await screen.findByText(/only a security admin can change this/i)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /save/i })).toBeDisabled();
      expect(requirementRadio()).toBeDisabled();
    });

    it("leaves the security admin's own controls alone", () => {
      render();
      expect(screen.queryByText(/only a security admin can change this/i)).not.toBeInTheDocument();
      expect(requirementRadio()).not.toBeDisabled();
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

    it("is the security admin's to change, like the rest of the page", () => {
      guildRole = "admin";
      render();

      expect(apiSwitch()).toBeDisabled();
    });
  });
});
