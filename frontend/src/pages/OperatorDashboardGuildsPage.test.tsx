import { act, fireEvent, screen } from "@testing-library/react";
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
    auth_options: ["providers", "restrictions"],
    banner_image_enabled: true,
    support_enabled: false,
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
    auth_options: ["providers"],
    banner_image_enabled: true,
    support_enabled: true,
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
    auth_options: [],
    banner_image_enabled: false,
    support_enabled: false,
  },
];

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

// Captured so a test can fire the save's own callbacks and check what the
// boxes do with a refusal.
let updateCallbacks: {
  onSuccess?: (row: (typeof guildsData)[number]) => void;
  onError?: (err: unknown) => void;
} = {};

vi.mock("@/hooks/useSettings", () => ({
  usePlatformGuilds: () => ({ data: guildsData, isLoading: false, isError: false }),
  useUpdateGuildStorage: (options: typeof updateCallbacks) => {
    updateCallbacks = options ?? {};
    return { mutate, isPending: false };
  },
}));

import { OperatorDashboardGuildsPage } from "./OperatorDashboardGuildsPage";

const renderPage = () =>
  renderWithProviders(<OperatorDashboardGuildsPage />, {
    auth: { user: buildUser({ role: "owner" }) },
  });

/** Open one community's operator settings. Everything editable lives there. */
const openSheet = async (user: ReturnType<typeof userEvent.setup>, guildName: string) => {
  expect(await screen.findByText(guildName)).toBeInTheDocument();
  await user.click(screen.getByLabelText(`Manage settings for ${guildName}`));
  return screen.getByRole("dialog");
};

const storageInput = () => screen.getByLabelText("Storage limit") as HTMLInputElement;
const userLimitInput = () => screen.getByLabelText("Members") as HTMLInputElement;

describe("OperatorDashboardGuildsPage", () => {
  beforeEach(() => {
    mutate.mockClear();
    mintHandoff.mockReset();
    billingConfig = { url: "https://billing.example.com", operator_handoff: true };
  });

  describe("the table", () => {
    it("summarises each community without editing anything", async () => {
      renderPage();

      expect(await screen.findByText("Capped Community")).toBeInTheDocument();
      expect(screen.getByText("7")).toBeInTheDocument(); // id column
      expect(screen.getByText("3 / 10")).toBeInTheDocument(); // members over cap
      expect(screen.getByText("10 GB")).toBeInTheDocument(); // storage cap
      // The community with no caps says so rather than showing a blank.
      expect(screen.getAllByText("No limit").length).toBeGreaterThan(0);
      // Nothing in the table is an editor any more.
      expect(screen.queryByLabelText("Storage limit")).toBeNull();
    });
  });

  describe("storage limit", () => {
    it("pre-fills the cap in GB, blank meaning unlimited", async () => {
      const user = userEvent.setup();
      renderPage();

      await openSheet(user, "Capped Community");
      expect(storageInput().value).toBe("10");
    });

    it("auto-saves the new cap on blur, converting GB to bytes", async () => {
      const user = userEvent.setup();
      renderPage();

      await openSheet(user, "Open Community");
      const input = storageInput();
      expect(input.value).toBe("");
      fireEvent.change(input, { target: { value: "5" } });
      fireEvent.blur(input);

      expect(mutate).toHaveBeenCalledWith({
        guildId: 8,
        data: { max_storage_bytes: 5 * GIB },
      });
    });

    it("does not save when the value is left unchanged", async () => {
      const user = userEvent.setup();
      renderPage();

      await openSheet(user, "Capped Community");
      fireEvent.blur(storageInput());

      expect(mutate).not.toHaveBeenCalled();
    });

    it("reverts an invalid entry on blur without saving", async () => {
      const user = userEvent.setup();
      renderPage();

      await openSheet(user, "Open Community");
      const input = storageInput();
      fireEvent.change(input, { target: { value: "-3" } });
      fireEvent.blur(input);

      expect(mutate).not.toHaveBeenCalled();
      expect(input.value).toBe(""); // snapped back to unlimited
    });
  });

  describe("member limit", () => {
    it("auto-saves the new cap on blur", async () => {
      const user = userEvent.setup();
      renderPage();

      await openSheet(user, "Open Community");
      const input = userLimitInput();
      fireEvent.change(input, { target: { value: "25" } });
      fireEvent.blur(input);

      expect(mutate).toHaveBeenCalledWith({ guildId: 8, data: { max_users: 25 } });
    });

    it("clearing the cap saves null, which is unlimited", async () => {
      const user = userEvent.setup();
      renderPage();

      await openSheet(user, "Capped Community");
      const input = userLimitInput();
      fireEvent.change(input, { target: { value: "" } });
      fireEvent.blur(input);

      expect(mutate).toHaveBeenCalledWith({ guildId: 7, data: { max_users: null } });
    });

    it.each([
      ["zero", "0"],
      ["a negative number", "-2"],
      ["a fraction", "2.5"],
    ])("reverts %s without saving", async (_label, value) => {
      const user = userEvent.setup();
      renderPage();

      await openSheet(user, "Capped Community");
      const input = userLimitInput();
      fireEvent.change(input, { target: { value } });
      fireEvent.blur(input);

      expect(mutate).not.toHaveBeenCalled();
      expect(input.value).toBe("10"); // back to the persisted cap
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

  describe("a refused save", () => {
    it("puts the stored value back rather than leaving the rejected one", async () => {
      const user = userEvent.setup();
      renderPage();

      await openSheet(user, "Capped Community");
      const input = storageInput();
      expect(input.value).toBe("10");

      fireEvent.change(input, { target: { value: "99" } });
      fireEvent.blur(input);
      expect(mutate).toHaveBeenCalled();

      act(() => updateCallbacks.onError?.(new Error("nope")));
      expect(storageInput().value).toBe("10");
    });

    it("shows what a save actually stored, not what was typed", async () => {
      const user = userEvent.setup();
      renderPage();

      await openSheet(user, "Capped Community");
      const input = storageInput();
      fireEvent.change(input, { target: { value: "5.0" } });
      fireEvent.blur(input);

      act(() =>
        updateCallbacks.onSuccess?.({
          ...guildsData[0],
          max_storage_bytes: 5 * GIB,
        })
      );
      expect(storageInput().value).toBe("5");
    });
  });

  describe("per-community sign-in grants", () => {
    const grant = (name: string) => screen.getByLabelText(name);

    it("shows which grants the community holds", async () => {
      const user = userEvent.setup();
      renderPage();

      await openSheet(user, "Open Community");
      expect(grant("Its own sign-in")).toBeChecked();
      expect(grant("Its own security standard")).not.toBeChecked();
    });

    it("offers both to a community holding neither", async () => {
      const user = userEvent.setup();
      renderPage();

      await openSheet(user, "Full Community");
      expect(grant("Its own sign-in")).not.toBeChecked();
      expect(grant("Its own security standard")).not.toBeChecked();
      // Neither waits on the other.
      expect(grant("Its own sign-in")).toBeEnabled();
      expect(grant("Its own security standard")).toBeEnabled();

      await user.click(grant("Its own sign-in"));
      expect(mutate).toHaveBeenCalledWith({
        guildId: 9,
        data: { auth_options: ["providers"] },
      });
    });

    it("grants the security standard on its own", async () => {
      const user = userEvent.setup();
      renderPage();

      await openSheet(user, "Full Community");
      await user.click(grant("Its own security standard"));

      expect(mutate).toHaveBeenCalledWith({
        guildId: 9,
        data: { auth_options: ["restrictions"] },
      });
    });

    it("adds the security standard to a community that already signs people in", async () => {
      const user = userEvent.setup();
      renderPage();

      await openSheet(user, "Open Community");
      await user.click(grant("Its own security standard"));

      expect(mutate).toHaveBeenCalledWith({
        guildId: 8,
        data: { auth_options: ["providers", "restrictions"] },
      });
    });

    it("withdraws one grant and leaves the other in place", async () => {
      const user = userEvent.setup();
      renderPage();

      await openSheet(user, "Capped Community");
      expect(grant("Its own sign-in")).toBeChecked();
      expect(grant("Its own security standard")).toBeChecked();

      await user.click(grant("Its own security standard"));
      expect(mutate).toHaveBeenCalledWith({
        guildId: 7,
        data: { auth_options: ["providers"] },
      });
    });
  });

  describe("feature entitlements", () => {
    it("sets the banner entitlement, which had no control before", async () => {
      const user = userEvent.setup();
      renderPage();

      await openSheet(user, "Capped Community");
      await user.click(screen.getByLabelText("Banner artwork"));

      expect(mutate).toHaveBeenCalledWith({
        guildId: 7,
        data: { banner_image_enabled: false },
      });
    });

    it("sets the help-request entitlement", async () => {
      const user = userEvent.setup();
      renderPage();

      await openSheet(user, "Capped Community");
      await user.click(screen.getByLabelText("Help requests"));

      expect(mutate).toHaveBeenCalledWith({
        guildId: 7,
        data: { support_enabled: true },
      });
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
