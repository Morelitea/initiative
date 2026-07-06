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
    name: "Capped Guild",
    member_count: 3,
    max_storage_bytes: 10 * GIB,
    max_users: 10,
    status: "active",
    status_changed_at: null,
  },
  {
    id: 8,
    name: "Open Guild",
    member_count: 0,
    max_storage_bytes: null,
    max_users: null,
    status: "active",
    status_changed_at: null,
  },
  {
    id: 9,
    name: "Full Guild",
    member_count: 12,
    max_storage_bytes: null,
    max_users: 10,
    status: "suspended",
    status_changed_at: "2026-07-05T00:00:00Z",
  },
];

vi.mock("@/hooks/useSettings", () => ({
  usePlatformGuilds: () => ({ data: guildsData, isLoading: false, isError: false }),
  useUpdateGuildStorage: () => ({ mutate, isPending: false }),
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
  });

  describe("storage limits", () => {
    it("pre-fills each guild's current cap in GB (blank = unlimited)", async () => {
      renderPage();

      expect(await screen.findByText("Capped Guild")).toBeInTheDocument();
      expect(screen.getByText("7")).toBeInTheDocument(); // id column
      expect(storageInput("Capped Guild").value).toBe("10");
      expect(storageInput("Open Guild").value).toBe("");
    });

    it("auto-saves the new cap on blur, converting GB to bytes", async () => {
      renderPage();

      const input = await screen.findByLabelText("Storage limit for Open Guild in GB");
      fireEvent.change(input, { target: { value: "5" } });
      fireEvent.blur(input);

      expect(mutate).toHaveBeenCalledWith({
        guildId: 8,
        data: { max_storage_bytes: 5 * GIB },
      });
    });

    it("does not save when the value is left unchanged", async () => {
      renderPage();

      fireEvent.blur(await screen.findByLabelText("Storage limit for Capped Guild in GB"));

      expect(mutate).not.toHaveBeenCalled();
    });

    it("reverts an invalid entry on blur without saving", async () => {
      renderPage();

      const input = storageInput("Open Guild");
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
      expect(await screen.findByText("Capped Guild")).toBeInTheDocument();
      expect(userLimitInput("Capped Guild").value).toBe("10");
      // Unlimited: blank input (placeholder renders "Unlimited").
      expect(userLimitInput("Open Guild").value).toBe("");
      // The slash separators render one per row.
      expect(screen.getAllByText("/")).toHaveLength(guildsData.length);
    });

    it("auto-saves the new user cap on blur", async () => {
      renderPage();

      const input = userLimitInput("Open Guild");
      fireEvent.change(input, { target: { value: "25" } });
      fireEvent.blur(input);

      expect(mutate).toHaveBeenCalledWith({ guildId: 8, data: { max_users: 25 } });
    });

    it("commits on Enter", async () => {
      renderPage();

      const input = userLimitInput("Open Guild");
      input.focus(); // Enter calls blur(), which only fires on the focused element
      fireEvent.change(input, { target: { value: "4" } });
      fireEvent.keyDown(input, { key: "Enter" });

      expect(mutate).toHaveBeenCalledWith({ guildId: 8, data: { max_users: 4 } });
    });

    it("clearing the cap saves null (switch back to unlimited)", async () => {
      renderPage();

      const input = userLimitInput("Capped Guild");
      fireEvent.change(input, { target: { value: "" } });
      fireEvent.blur(input);

      expect(mutate).toHaveBeenCalledWith({ guildId: 7, data: { max_users: null } });
    });

    it("does not save when the cap is left unchanged", async () => {
      renderPage();

      fireEvent.blur(userLimitInput("Capped Guild"));

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

      const input = userLimitInput("Capped Guild");
      fireEvent.change(input, { target: { value } });
      fireEvent.blur(input);

      expect(mutate).not.toHaveBeenCalled();
      expect(input.value).toBe("10"); // snapped back to the persisted cap
    });

    it("flags a guild that is over its cap (existing members are never removed)", async () => {
      renderPage();

      // Full Guild has 12 members against a cap of 10 — the count carries the
      // over-limit hint (and destructive styling), but the cap stays editable.
      expect(
        await screen.findByTitle("Full Guild has more members than its current limit allows.")
      ).toHaveTextContent("12");
      expect(userLimitInput("Full Guild").value).toBe("10");
    });
  });

  describe("lifecycle status", () => {
    const statusControl = (guildName: string) => screen.getByLabelText(`Status for ${guildName}`);

    it("shows each guild's current status", async () => {
      renderPage();

      expect(await screen.findByText("Capped Guild")).toBeInTheDocument();
      expect(statusControl("Capped Guild")).toHaveTextContent("Active");
      expect(statusControl("Full Guild")).toHaveTextContent("Suspended");
    });

    it("applies a non-suspend change immediately (no confirm)", async () => {
      const user = userEvent.setup();
      renderPage();

      await user.click(statusControl("Capped Guild"));
      await user.click(await screen.findByRole("option", { name: "Read-only" }));

      expect(mutate).toHaveBeenCalledWith({ guildId: 7, data: { status: "read_only" } });
    });

    it("gates suspend behind a confirm dialog", async () => {
      const user = userEvent.setup();
      renderPage();

      await user.click(statusControl("Capped Guild"));
      await user.click(await screen.findByRole("option", { name: "Suspended" }));

      // Not applied yet — the confirm dialog is shown first.
      expect(mutate).not.toHaveBeenCalled();
      expect(await screen.findByText("Suspend Capped Guild?")).toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "Suspend guild" }));
      expect(mutate).toHaveBeenCalledWith({ guildId: 7, data: { status: "suspended" } });
    });
  });
});
