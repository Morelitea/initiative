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
const restore = vi.fn();

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
    purge_at: null,
    has_seat: true,
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
    purge_at: null,
    has_seat: true,
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
    purge_at: null,
    has_seat: true,
    auth_options: [],
    banner_image_enabled: false,
    support_enabled: false,
  },
  {
    id: 10,
    name: "Gone Community",
    member_count: 4,
    tier_name: null,
    max_storage_bytes: null,
    max_users: null,
    status: "deleted",
    status_changed_at: "2026-09-01T00:00:00Z",
    purge_at: "2026-11-30T00:00:00Z",
    has_seat: true,
    auth_options: [],
    banner_image_enabled: true,
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
  useRestoreGuild: () => ({ mutate: restore, isPending: false }),
}));

vi.mock("@/hooks/useAdmin", () => ({
  usePlatformUsers: () => ({ data: [], isLoading: false }),
}));

import { OperatorDashboardGuildsPage } from "./OperatorDashboardGuildsPage";

const renderPage = () =>
  renderWithProviders(<OperatorDashboardGuildsPage />, {
    auth: { user: buildUser({ role: "owner" }) },
  });

/** Render the page, ready to be clicked. */
const mounted = () => {
  const user = userEvent.setup();
  renderPage();
  return user;
};

/** Render and open one community's operator settings, which is where
 *  everything editable lives. */
const openSheet = async (guildName: string) => {
  const user = mounted();
  expect(await screen.findByText(guildName)).toBeInTheDocument();
  await user.click(screen.getByLabelText(`Manage settings for ${guildName}`));
  return user;
};

const storageInput = () => screen.getByLabelText("Storage limit") as HTMLInputElement;
const userLimitInput = () => screen.getByLabelText("Members") as HTMLInputElement;

/** Type into a box and leave it, which is the only way either cap is saved. */
const typeAndLeave = (input: HTMLInputElement, value: string) => {
  fireEvent.change(input, { target: { value } });
  fireEvent.blur(input);
};

describe("OperatorDashboardGuildsPage", () => {
  beforeEach(() => {
    mutate.mockClear();
    restore.mockClear();
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

  // Both caps are the same editor: pre-filled from what is stored, saved on
  // blur, blank meaning no limit at all, and anything the field cannot mean
  // snapped back rather than sent. Capped Community holds both caps at 10;
  // Open Community holds neither.
  describe.each([
    {
      what: "storage limit",
      input: storageInput,
      stored: "10",
      typed: "5",
      saves: { max_storage_bytes: 5 * GIB },
      cleared: { max_storage_bytes: null },
      rejects: [["a negative number", "-3"]],
    },
    {
      what: "member limit",
      input: userLimitInput,
      stored: "10",
      typed: "25",
      saves: { max_users: 25 },
      cleared: { max_users: null },
      rejects: [
        ["zero", "0"],
        ["a negative number", "-2"],
        ["a fraction", "2.5"],
      ],
    },
  ])("$what", ({ input, stored, typed, saves, cleared, rejects }) => {
    it("pre-fills the cap that is stored", async () => {
      await openSheet("Capped Community");

      expect(input().value).toBe(stored);
    });

    it("auto-saves a new cap on blur, converting it to what the API stores", async () => {
      await openSheet("Open Community");

      expect(input().value).toBe(""); // blank meaning unlimited
      typeAndLeave(input(), typed);

      expect(mutate).toHaveBeenCalledWith({ guildId: 8, data: saves });
    });

    it("does not save when the value is left unchanged", async () => {
      await openSheet("Capped Community");

      fireEvent.blur(input());

      expect(mutate).not.toHaveBeenCalled();
    });

    it("saves clearing the cap as no limit at all", async () => {
      await openSheet("Capped Community");

      typeAndLeave(input(), "");

      expect(mutate).toHaveBeenCalledWith({ guildId: 7, data: cleared });
    });

    it.each(rejects)("reverts %s without saving", async (_label, value) => {
      await openSheet("Capped Community");

      typeAndLeave(input(), value);

      expect(mutate).not.toHaveBeenCalled();
      expect(input().value).toBe(stored); // back to the persisted cap
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
      const user = mounted();

      await user.click(statusControl("Capped Community"));
      await user.click(await screen.findByRole("option", { name: "Read-only" }));

      expect(mutate).toHaveBeenCalledWith({ guildId: 7, data: { status: "read_only" } });
    });

    it("gates suspend behind a confirm dialog", async () => {
      const user = mounted();

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
      await openSheet("Capped Community");
      const input = storageInput();
      expect(input.value).toBe("10");

      typeAndLeave(input, "99");
      expect(mutate).toHaveBeenCalled();

      act(() => updateCallbacks.onError?.(new Error("nope")));
      expect(storageInput().value).toBe("10");
    });

    it("shows what a save actually stored, not what was typed", async () => {
      await openSheet("Capped Community");
      typeAndLeave(storageInput(), "5.0");

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
    const SIGN_IN = "Its own sign-in";
    const STANDARD = "Its own security standard";

    // Neither grant waits on the other, so a community holds either, both or
    // none — and both are offered either way.
    it.each([
      ["a community that signs its own people in", "Open Community", true, false],
      ["a community holding neither", "Full Community", false, false],
      ["a community holding both", "Capped Community", true, true],
    ])("shows which grants %s holds", async (_label, guildName, signIn, standard) => {
      await openSheet(guildName);

      expect(grant(SIGN_IN)).toBeEnabled();
      expect(grant(STANDARD)).toBeEnabled();
      if (signIn) expect(grant(SIGN_IN)).toBeChecked();
      else expect(grant(SIGN_IN)).not.toBeChecked();
      if (standard) expect(grant(STANDARD)).toBeChecked();
      else expect(grant(STANDARD)).not.toBeChecked();
    });

    // A click sends the whole set the community would then hold, so adding one
    // keeps the other and withdrawing one leaves the other in place.
    it.each([
      [
        "grants sign-in to a community holding neither",
        "Full Community",
        SIGN_IN,
        9,
        ["providers"],
      ],
      ["grants the security standard on its own", "Full Community", STANDARD, 9, ["restrictions"]],
      [
        "adds the security standard to a community that already signs people in",
        "Open Community",
        STANDARD,
        8,
        ["providers", "restrictions"],
      ],
      [
        "withdraws one grant and leaves the other in place",
        "Capped Community",
        STANDARD,
        7,
        ["providers"],
      ],
    ])("%s", async (_label, guildName, name, guildId, auth_options) => {
      const user = await openSheet(guildName);

      await user.click(grant(name));

      expect(mutate).toHaveBeenCalledWith({ guildId, data: { auth_options } });
    });
  });

  describe("feature entitlements", () => {
    // Neither of these had a control at all before; both are the operator's.
    it.each([
      ["the banner entitlement", "Banner artwork", { banner_image_enabled: false }],
      ["the help-request entitlement", "Help requests", { support_enabled: true }],
    ])("sets %s", async (_label, name, data) => {
      const user = await openSheet("Capped Community");

      await user.click(screen.getByLabelText(name));

      expect(mutate).toHaveBeenCalledWith({ guildId: 7, data });
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

    it.each([
      ["no billing portal is configured", null],
      [
        "the operator route into the portal is not wired",
        { url: "https://billing.example.com", operator_handoff: false },
      ],
    ])("is absent when %s", async (_label, billing) => {
      billingConfig = billing;
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

  describe("a deleted community", () => {
    it("shows a tag instead of the status control", async () => {
      renderPage();

      expect(await screen.findByText("Gone Community")).toBeInTheDocument();
      expect(screen.getByText("Deleted")).toBeInTheDocument();
      // No control at all: deleted is not a status you pick, so the row that
      // holds it offers nothing to pick with.
      expect(screen.queryByLabelText("Status for Gone Community")).not.toBeInTheDocument();
      // ...while a live community still has its dropdown.
      expect(screen.getByLabelText("Status for Capped Community")).toBeInTheDocument();
    });

    it("offers a restore with the date everything is destroyed on", async () => {
      await openSheet("Gone Community");

      // The purge date is an instant, not a calendar day, so it is drawn in
      // the reader's own timezone — computed here the same way rather than
      // written out, which would only pass in the timezone it was written in.
      const expected = new Date("2026-11-30T00:00:00Z").toLocaleDateString("en", {
        year: "numeric",
        month: "long",
        day: "numeric",
      });
      expect(
        screen.getByText(`Deleted. Everything in it is destroyed on ${expected}.`)
      ).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Restore community" })).toBeInTheDocument();
      // Its caps are shown but frozen — worth seeing while you decide, not
      // worth setting on a community nobody can reach.
      expect(userLimitInput()).toBeDisabled();
      expect(storageInput()).toBeDisabled();
    });

    it("restores it at the status the operator picks", async () => {
      const user = await openSheet("Gone Community");
      await user.click(screen.getByRole("button", { name: "Restore community" }));

      // This community still has somebody to run it, so the seat step is
      // skipped and the only question is what it comes back as.
      expect(screen.getByText("Choose what the community comes back as.")).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "Restore" }));

      expect(restore).toHaveBeenCalledWith({
        guildId: 10,
        data: { status: "active", seat_user_id: null },
      });
    });
  });
});
