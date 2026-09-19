import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AxiosError, AxiosHeaders } from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import { AUTH_FACTOR_REQUIRED_EVENT, type FactorChallengeDetail } from "@/api/client";

// What the server says about this community and this member. Flipped per test.
let guildRole = "superadmin";
let grantSettingsLevel: "admin" | "superadmin" | null = null;
let guildId = 4;
let authOptions: string[] | null = ["restrictions", "providers"];
let allowApiKeys: boolean | null = true;
let sessionLimit: boolean | null = false;
let grantedAuthSettings = {
  auth_options: ["restrictions", "providers"],
  allow_api_keys: true,
  enforce_compliance_session: false,
};
const connection = (id: number, providerId: number, slug: string, name: string) => ({
  id,
  provider_id: providerId,
  provider_slug: slug,
  provider_display_name: name,
  provider_icon: null,
  claim: null,
  claim_values: [],
  enabled: true,
  login_ready: true,
});
let connections = [
  connection(1, 11, "corp", "Corp SSO"),
  connection(2, 12, "contractors", "Contractors"),
];
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
  useGuildProviderConnections: () => ({ data: connections, isLoading: false }),
  useConnectableProviders: () => ({ data: [], isLoading: false }),
  useGuildLoginProviders: () => ({ data: { providers: [] } }),
  useConnectProvider: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateProviderConnection: () => ({ mutate: vi.fn(), isPending: false }),
  useDisconnectProvider: () => ({ mutate: vi.fn(), isPending: false }),
  useGuildClaimRules: () => ({
    data: { rules: [], reporting_provider_ids: [] },
    isLoading: false,
  }),
  useCreateClaimRule: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateClaimRule: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteClaimRule: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { SettingsGuildSecurityPage } from "./SettingsGuildSecurityPage";

const render = () =>
  renderWithProviders(<SettingsGuildSecurityPage />, { auth: { user: buildUser() } });

const requirementRadio = () => screen.getByLabelText(/require single sign-on/i);

/** The provider picker lists the same names the registry below does, so
 * choose from the open listbox rather than from the page. */
const chooseOption = async (user: ReturnType<typeof userEvent.setup>, name: string | RegExp) => {
  await user.click(await screen.findByRole("combobox"));
  await user.click(await screen.findByRole("option", { name }));
};

describe("SettingsGuildSecurityPage", () => {
  beforeEach(() => {
    savePolicy.mockClear();
    saveApiAccess.mockClear();
    saveSessionLimit.mockClear();
    refreshGuilds.mockClear();
    guildRole = "superadmin";
    grantSettingsLevel = null;
    guildId = 4;
    authOptions = ["restrictions", "providers"];
    allowApiKeys = true;
    sessionLimit = false;
    connections = [
      connection(1, 11, "corp", "Corp SSO"),
      connection(2, 12, "contractors", "Contractors"),
    ];
    grantedAuthSettings = {
      auth_options: ["restrictions", "providers"],
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

  describe("how the page is laid out", () => {
    /** Where each snippet falls in the rendered text, so order can be read. */
    const positions = (...snippets: string[]) => {
      const text = document.body.textContent ?? "";
      return snippets.map((snippet) => text.indexOf(snippet));
    };

    it("puts who gets in before the terms of a session", () => {
      render();

      const [whoGetsIn, onWhatTerms] = positions("Who gets in", "On what terms");
      expect(whoGetsIn).toBeGreaterThanOrEqual(0);
      expect(onWhatTerms).toBeGreaterThan(whoGetsIn);
    });

    it("asks for a requirement after the connections it can name", () => {
      // The requirement picks from the providers above it, and the rules
      // between them say where the people arriving on those providers land.
      render();

      const found = positions(
        "Which sign-ins are yours",
        "Where your people land",
        "Sign-in requirement",
        "Member sign-in link"
      );
      expect(found.every((index) => index >= 0)).toBe(true);
      expect(found).toEqual([...found].sort((a, b) => a - b));
    });

    it("puts session length before API access", () => {
      render();

      const [length, api] = positions("Session length", "API access");
      expect(length).toBeGreaterThanOrEqual(0);
      expect(api).toBeGreaterThan(length);
    });
  });

  describe("a community that has connected nothing", () => {
    it("leads with a prompt to set sign-in up", () => {
      connections = [];
      render();

      const prompt = screen.getByText(/nothing connected yet/i);
      const button = screen.getByRole("button", { name: /set up sign-in/i });
      expect(prompt).toBeInTheDocument();
      const text = document.body.textContent ?? "";
      expect(text.indexOf("Nothing connected yet")).toBeLessThan(
        text.indexOf("Which sign-ins are yours")
      );
      expect(button).toBeEnabled();
    });

    it("drops the prompt once something is connected", () => {
      render();

      expect(screen.queryByText(/nothing connected yet/i)).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /set up sign-in/i })).not.toBeInTheDocument();
    });
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

    it("has nothing to save until something changes", () => {
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
        auth_options: ["restrictions", "providers"],
        allow_api_keys: false,
        enforce_compliance_session: true,
      };

      render();

      expect(requirementRadio()).toBeInTheDocument();
      expect(screen.getByLabelText(/allow personal api keys/i)).not.toBeChecked();
      expect(screen.getByLabelText(/sign in again every twelve hours/i)).toBeChecked();
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

    it("asks for a passkey alongside the code", async () => {
      const user = userEvent.setup();
      render();

      await user.click(requirementRadio());
      await chooseOption(user, "Contractors");
      await user.click(screen.getByLabelText(/second factor/i));
      await user.click(screen.getByLabelText(/require a passkey/i));
      await user.click(screen.getByRole("button", { name: /save/i }));

      expect(savePolicy.mock.calls[0][0]).toEqual({
        policy: "required",
        provider_id: 12,
        require_methods: ["totp", "passkey"],
      });
    });

    it("asks for a passkey on its own", async () => {
      const user = userEvent.setup();
      render();

      await user.click(requirementRadio());
      await user.click(screen.getByLabelText(/require a passkey/i));
      await user.click(screen.getByRole("button", { name: /save/i }));

      expect(savePolicy.mock.calls[0][0]).toEqual({
        policy: "required",
        provider_id: null,
        require_methods: ["passkey"],
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

  describe("when the admin's own session does not meet the rule", () => {
    /** The save's refusal, as the server names what is missing. */
    const refuse = (unmet?: string, detail = "GUILD_AUTH_POLICY_SELF_UNSATISFIED") => {
      // Lower-cased, as axios hands a response's headers back.
      const headers = new AxiosHeaders(unmet ? { "x-auth-policy-unmet": unmet } : {});
      const error = new AxiosError("refused", "ERR_BAD_REQUEST");
      error.response = {
        status: 400,
        statusText: "",
        data: { detail },
        headers,
        config: { headers: new AxiosHeaders() },
      };
      const sent = savePolicy.mock.calls[0][1] as { onError: (err: unknown) => void };
      act(() => sent.onError(error));
    };

    /** What the page asked the global dialog for, if it asked. */
    let asked: FactorChallengeDetail[] = [];
    const record = (event: Event) => {
      asked.push((event as CustomEvent<FactorChallengeDetail>).detail);
    };
    beforeEach(() => {
      asked = [];
      window.addEventListener(AUTH_FACTOR_REQUIRED_EVENT, record);
    });
    afterEach(() => {
      window.removeEventListener(AUTH_FACTOR_REQUIRED_EVENT, record);
    });

    it("offers the named provider's sign-in", async () => {
      const user = userEvent.setup();
      render();

      await user.click(requirementRadio());
      await chooseOption(user, "Contractors");
      await user.click(screen.getByRole("button", { name: /save/i }));
      refuse("provider");

      expect(screen.getByText(/hasn't signed in with Contractors/i)).toBeInTheDocument();
      // The choice is still there to save again once the session carries it.
      expect(screen.getByRole("combobox")).toHaveTextContent("Contractors");
      expect(screen.getByRole("button", { name: /save/i })).toBeEnabled();
    });

    it("asks for a code where the rule wants one", async () => {
      const user = userEvent.setup();
      render();

      await user.click(requirementRadio());
      await chooseOption(user, "Contractors");
      await user.click(screen.getByLabelText(/second factor/i));
      await user.click(screen.getByRole("button", { name: /save/i }));
      refuse("totp");

      expect(
        screen.getByText(/enter a code from your authenticator app first/i)
      ).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: /^enter a code$/i }));

      expect(asked).toEqual([{ guildId: 4, kind: "totp" }]);
      expect(screen.getByLabelText(/second factor/i)).toBeChecked();
      expect(screen.getByRole("button", { name: /save/i })).toBeEnabled();
    });

    it("asks for the passkey where the rule wants one", async () => {
      const user = userEvent.setup();
      render();

      await user.click(requirementRadio());
      await user.click(screen.getByLabelText(/require a passkey/i));
      await user.click(screen.getByRole("button", { name: /save/i }));
      refuse("passkey");

      expect(screen.getByText(/present your passkey first/i)).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: /^present passkey$/i }));

      expect(asked).toEqual([{ guildId: 4, kind: "passkey" }]);
      expect(screen.getByLabelText(/require a passkey/i)).toBeChecked();
      expect(screen.getByRole("button", { name: /save/i })).toBeEnabled();
    });

    it("still says something when the server names nothing", async () => {
      // An older server answers the same refusal with no header on it.
      const user = userEvent.setup();
      render();

      await user.click(requirementRadio());
      await user.click(screen.getByLabelText(/require a passkey/i));
      await user.click(screen.getByRole("button", { name: /save/i }));
      refuse();

      expect(
        screen.getByText(/sign in with that provider yourself before requiring it/i)
      ).toBeInTheDocument();
      expect(screen.getByLabelText(/require a passkey/i)).toBeChecked();
      expect(screen.getByRole("button", { name: /save/i })).toBeEnabled();
    });
  });

  describe("what each grant brings with it", () => {
    it("renders nothing where the operator has granted neither", () => {
      authOptions = [];
      const { container } = render();

      expect(container).toBeEmptyDOMElement();
    });

    it("shows only the terms half where that is all that is granted", () => {
      authOptions = ["restrictions"];
      render();

      expect(screen.getByLabelText(/allow personal api keys/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/sign in again every twelve hours/i)).toBeInTheDocument();
      expect(screen.queryByText("Who gets in")).not.toBeInTheDocument();
      expect(screen.queryByLabelText(/require single sign-on/i)).not.toBeInTheDocument();
    });

    it("shows only the sign-in half where that is all that is granted", () => {
      authOptions = ["providers"];
      render();

      expect(requirementRadio()).toBeInTheDocument();
      expect(screen.getByText(/member sign-in link/i)).toBeInTheDocument();
      expect(screen.queryByText("On what terms")).not.toBeInTheDocument();
      expect(screen.queryByLabelText(/allow personal api keys/i)).not.toBeInTheDocument();
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
  });

  describe("how often members sign in again", () => {
    const limitSwitch = () => screen.getByLabelText(/sign in again every twelve hours/i);

    it("saves as it is switched, with no button to press", async () => {
      const user = userEvent.setup();
      render();

      expect(limitSwitch()).not.toBeChecked();
      await user.click(limitSwitch());

      expect(saveSessionLimit).toHaveBeenCalledTimes(1);
      expect(saveSessionLimit.mock.calls[0][0]).toEqual({ enforce_compliance_session: true });
    });

    it("says what it is for in one line either way", () => {
      sessionLimit = true;
      render();

      expect(limitSwitch()).toBeChecked();
      expect(screen.getByText(/cap how long people stay signed in/i)).toBeInTheDocument();
    });

    it("is the seat's, not an ordinary admin's", () => {
      guildRole = "admin";
      render();

      expect(screen.queryByLabelText(/sign in again every twelve hours/i)).not.toBeInTheDocument();
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
      view.rerender(<SettingsGuildSecurityPage />);

      expect(limitSwitch()).not.toBeChecked();

      act(() => pending.onError(new Error("old community failed")));
      expect(screen.queryByText("Could not save the session limit")).not.toBeInTheDocument();
    });
  });
});
