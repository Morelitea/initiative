import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

const GIB = 1024 ** 3;

// One mutate spy shared by every row's useUpdateGuildStorage (the hook is mocked
// to return the same object), so any row's edit resolves to this spy. Storage
// edits and user-limit edits are told apart by the `data` payload they send
// ({ max_storage_bytes } vs { max_users }).
const mutate = vi.fn();

const guildsData = [
  {
    id: 7,
    name: "Capped Community",
    member_count: 3,
    tier_name: "Bespoke Plan",
    max_storage_bytes: 10 * GIB,
    max_users: 10,
    status: "active",
    status_changed_at: null,
    guild_auth_enabled: false,
  },
  {
    id: 8,
    name: "Open Community",
    member_count: 0,
    tier_name: null,
    max_storage_bytes: null,
    max_users: null,
    status: "active",
    status_changed_at: null,
    guild_auth_enabled: true,
  },
  {
    id: 9,
    name: "Full Community",
    member_count: 12,
    tier_name: "Bespoke Plan",
    max_storage_bytes: null,
    max_users: 10,
    status: "suspended",
    status_changed_at: "2026-07-05T00:00:00Z",
    guild_auth_enabled: false,
  },
];

// The guild-auth toggle column only renders under per-guild posture; flip this
// before a render to exercise both cases.
let authScope: "platform" | "guild" = "platform";

// The billing column only renders when a portal is configured; flip this to
// exercise the self-hosted case (no portal, no column).
let billingConfig: { url: string; operator_handoff: boolean } | null = {
  url: "https://billing.example.com",
  operator_handoff: true,
};

const mintHandoff = vi.fn();

vi.mock("@/hooks/useAppConfig", () => ({
  useAppConfig: () => ({ billing: billingConfig }),
}));

vi.mock("@/api/generated/settings/settings", () => ({
  createPlatformGuildBillingServiceHandoffApiV1SettingsGuildsGuildIdBillingServiceHandoffPost: (
    guildId: number
  ) => mintHandoff(guildId),
}));

vi.mock("@/hooks/useSettings", () => ({
  usePlatformGuilds: () => ({ data: guildsData, isLoading: false, isError: false }),
  useUpdateGuildStorage: () => ({ mutate, isPending: false }),
  useInterfaceSettings: () => ({ data: { auth_scope: authScope } }),
}));

import { AdminDashboardGuildsPage } from "./AdminDashboardGuildsPage";

const renderPage = () =>
  renderWithProviders(<AdminDashboardGuildsPage />, {
    auth: { user: buildUser({ role: "owner" }) },
  });

const storageInput = (guildName: string) =>
  screen.getByLabelText(`Storage limit for ${guildName} in GB`) as HTMLInputElement;
const userLimitInput = (guildName: string) =>
  screen.getByLabelText(`User limit for ${guildName}`) as HTMLInputElement;

describe("AdminDashboardGuildsPage", () => {
  beforeEach(() => {
    mutate.mockClear();
    mintHandoff.mockReset();
    authScope = "platform";
    billingConfig = { url: "https://billing.example.com", operator_handoff: true };
  });

  describe("storage limits", () => {
    it("pre-fills each community's current cap in GB (blank = unlimited)", async () => {
      renderPage();

      expect(await screen.findByText("Capped Community")).toBeInTheDocument();
      expect(screen.getByText("7")).toBeInTheDocument(); // id column
      expect(storageInput("Capped Community").value).toBe("10");
      expect(storageInput("Open Community").value).toBe("");
    });

    it("auto-saves the new cap on blur, converting GB to bytes", async () => {
      renderPage();

      const input = await screen.findByLabelText("Storage limit for Open Community in GB");
      fireEvent.change(input, { target: { value: "5" } });
      fireEvent.blur(input);

      expect(mutate).toHaveBeenCalledWith({
        guildId: 8,
        data: { max_storage_bytes: 5 * GIB },
      });
    });

    it("does not save when the value is left unchanged", async () => {
      renderPage();

      fireEvent.blur(await screen.findByLabelText("Storage limit for Capped Community in GB"));

      expect(mutate).not.toHaveBeenCalled();
    });

    it("reverts an invalid entry on blur without saving", async () => {
      renderPage();

      const input = storageInput("Open Community");
      fireEvent.change(input, { target: { value: "-3" } });
      fireEvent.blur(input);

      expect(mutate).not.toHaveBeenCalled();
      expect(input.value).toBe(""); // snapped back to unlimited
    });
  });

  describe("user limits", () => {
    it("shows member count over an editable cap (the 3/unlimited display)", async () => {
      renderPage();

      // Capped: count 3 with the cap 10 pre-filled in the input.
      expect(await screen.findByText("Capped Community")).toBeInTheDocument();
      expect(userLimitInput("Capped Community").value).toBe("10");
      // Unlimited: blank input (placeholder renders "Unlimited").
      expect(userLimitInput("Open Community").value).toBe("");
      // The slash separators render one per row.
      expect(screen.getAllByText("/")).toHaveLength(guildsData.length);
    });

    it("auto-saves the new user cap on blur", async () => {
      renderPage();

      const input = userLimitInput("Open Community");
      fireEvent.change(input, { target: { value: "25" } });
      fireEvent.blur(input);

      expect(mutate).toHaveBeenCalledWith({ guildId: 8, data: { max_users: 25 } });
    });

    it("commits on Enter", async () => {
      renderPage();

      const input = userLimitInput("Open Community");
      input.focus(); // Enter calls blur(), which only fires on the focused element
      fireEvent.change(input, { target: { value: "4" } });
      fireEvent.keyDown(input, { key: "Enter" });

      expect(mutate).toHaveBeenCalledWith({ guildId: 8, data: { max_users: 4 } });
    });

    it("clearing the cap saves null (switch back to unlimited)", async () => {
      renderPage();

      const input = userLimitInput("Capped Community");
      fireEvent.change(input, { target: { value: "" } });
      fireEvent.blur(input);

      expect(mutate).toHaveBeenCalledWith({ guildId: 7, data: { max_users: null } });
    });

    it("does not save when the cap is left unchanged", async () => {
      renderPage();

      fireEvent.blur(userLimitInput("Capped Community"));

      expect(mutate).not.toHaveBeenCalled();
    });

    // Non-numeric text ("abc") can't be entered at all — the type="number"
    // input strips it — so the meaningful invalid cases are numeric but
    // out-of-range: zero, negative, or fractional.
    it.each([
      ["zero", "0"],
      ["a negative number", "-5"],
      ["a fraction", "2.5"],
    ])("reverts %s without saving", async (_label, value) => {
      renderPage();

      const input = userLimitInput("Capped Community");
      fireEvent.change(input, { target: { value } });
      fireEvent.blur(input);

      expect(mutate).not.toHaveBeenCalled();
      expect(input.value).toBe("10"); // snapped back to the persisted cap
    });

    it("flags a community that is over its cap (existing members are never removed)", async () => {
      renderPage();

      // Full Guild has 12 members against a cap of 10 — the count carries the
      // over-limit hint (and destructive styling), but the cap stays editable.
      expect(
        await screen.findByTitle("Full Community has more members than its current limit allows.")
      ).toHaveTextContent("12");
      expect(userLimitInput("Full Community").value).toBe("10");
    });
  });

  describe("lifecycle status", () => {
    const statusControl = (guildName: string) => screen.getByLabelText(`Status for ${guildName}`);

    it("shows each community's current status", async () => {
      renderPage();

      expect(await screen.findByText("Capped Community")).toBeInTheDocument();
      expect(statusControl("Capped Community")).toHaveTextContent("Active");
      expect(statusControl("Full Community")).toHaveTextContent("Suspended");
    });

    it("applies a non-suspend change immediately (no confirm)", async () => {
      const user = userEvent.setup();
      renderPage();

      await user.click(statusControl("Capped Community"));
      await user.click(await screen.findByRole("option", { name: "Read-only" }));

      expect(mutate).toHaveBeenCalledWith({ guildId: 7, data: { status: "read_only" } });
    });

    it("gates suspend behind a confirm dialog", async () => {
      const user = userEvent.setup();
      renderPage();

      await user.click(statusControl("Capped Community"));
      await user.click(await screen.findByRole("option", { name: "Suspended" }));

      // Not applied yet — the confirm dialog is shown first.
      expect(mutate).not.toHaveBeenCalled();
      expect(await screen.findByText("Suspend Capped Community?")).toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "Suspend community" }));
      expect(mutate).toHaveBeenCalledWith({ guildId: 7, data: { status: "suspended" } });
    });
  });

  describe("per-community sign-in toggle", () => {
    const authToggle = (guildName: string) =>
      screen.getByLabelText(`Per-community sign-in for ${guildName}`);

    it("is hidden under platform posture", async () => {
      renderPage(); // authScope defaults to "platform"

      expect(await screen.findByText("Capped Community")).toBeInTheDocument();
      expect(screen.queryByLabelText("Per-community sign-in for Capped Community")).toBeNull();
    });

    it("renders each community's entitlement under community posture", async () => {
      authScope = "guild";
      renderPage();

      expect(await screen.findByText("Capped Community")).toBeInTheDocument();
      expect(authToggle("Capped Community")).toHaveAttribute("aria-checked", "false");
      expect(authToggle("Open Community")).toHaveAttribute("aria-checked", "true");
    });

    it("turns the entitlement on", async () => {
      authScope = "guild";
      const user = userEvent.setup();
      renderPage();

      await user.click(authToggle("Capped Community"));
      expect(mutate).toHaveBeenCalledWith({ guildId: 7, data: { guild_auth_enabled: true } });
    });

    it("turns the entitlement off", async () => {
      authScope = "guild";
      const user = userEvent.setup();
      renderPage();

      await user.click(authToggle("Open Community"));
      expect(mutate).toHaveBeenCalledWith({ guildId: 8, data: { guild_auth_enabled: false } });
    });
  });

  describe("billing column", () => {
    it("labels each button with the community's plan, verbatim", async () => {
      renderPage();

      expect(await screen.findByText("Capped Community")).toBeInTheDocument();
      expect(screen.getByLabelText("Open billing for Capped Community")).toHaveTextContent(
        "Bespoke Plan"
      );
      // No plan named by billing -> neutral label, never an invented tier.
      expect(screen.getByLabelText("Open billing for Open Community")).toHaveTextContent("No plan");
    });

    it("is absent when no billing portal is configured", async () => {
      billingConfig = null;
      renderPage();

      expect(await screen.findByText("Capped Community")).toBeInTheDocument();
      expect(screen.queryByLabelText("Open billing for Capped Community")).not.toBeInTheDocument();
    });

    it("is absent when the operator route into the portal is not wired", async () => {
      billingConfig = { url: "https://billing.example.com", operator_handoff: false };
      renderPage();

      expect(await screen.findByText("Capped Community")).toBeInTheDocument();
      expect(screen.queryByLabelText("Open billing for Capped Community")).not.toBeInTheDocument();
    });

    it("mints a handoff for that community and opens the portal with it", async () => {
      const location = { href: "" };
      const tab = { opener: {} as unknown, location, close: vi.fn() };
      const openSpy = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
      mintHandoff.mockResolvedValue({ handoff_token: "tok-123", expires_in_seconds: 60 });

      renderPage();
      await userEvent.click(await screen.findByLabelText("Open billing for Capped Community"));

      expect(mintHandoff).toHaveBeenCalledWith(7);
      // The console reads the guild off the session it exchanges, so the URL
      // never names one; the token rides in the fragment, which is not sent to
      // the server. The key is `support_handoff` — the console ignores the
      // `handoff` the guild-admin flow uses.
      const [path, fragment] = location.href.split("#");
      expect(path).toBe("https://billing.example.com/support?lang=en");
      expect(fragment).toBe("support_handoff=tok-123");
      expect(tab.opener).toBeNull();

      openSpy.mockRestore();
    });

    it("closes the blank tab when minting fails", async () => {
      const tab = { opener: {} as unknown, location: { href: "" }, close: vi.fn() };
      const openSpy = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
      mintHandoff.mockRejectedValue(new Error("nope"));

      renderPage();
      await userEvent.click(await screen.findByLabelText("Open billing for Capped Community"));

      expect(tab.close).toHaveBeenCalled();
      expect(tab.location.href).toBe("");

      openSpy.mockRestore();
    });
  });
});
