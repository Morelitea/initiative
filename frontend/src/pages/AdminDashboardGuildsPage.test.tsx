import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

const GIB = 1024 ** 3;

// One mutate spy shared by every row's useUpdateGuildStorage (the hook is mocked
// to return the same object), so any row's edit resolves to this spy.
const mutate = vi.fn();

const guildsData = [
  { id: 7, name: "Capped Guild", member_count: 3, max_storage_bytes: 10 * GIB },
  { id: 8, name: "Open Guild", member_count: 0, max_storage_bytes: null },
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

const limitInput = (guildName: string) =>
  screen.getByLabelText(`Storage limit for ${guildName} in GB`) as HTMLInputElement;

describe("AdminDashboardGuildsPage", () => {
  beforeEach(() => {
    mutate.mockClear();
  });

  it("lists guilds with id, members, and the current cap pre-filled in GB", async () => {
    renderPage();

    expect(await screen.findByText("Capped Guild")).toBeInTheDocument();
    // Guild id is shown as its own column.
    expect(screen.getByText("7")).toBeInTheDocument();

    expect(limitInput("Capped Guild").value).toBe("10");
    // An unlimited guild shows a blank input (placeholder = "Unlimited").
    expect(limitInput("Open Guild").value).toBe("");
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

    const input = await screen.findByLabelText("Storage limit for Capped Guild in GB");
    fireEvent.blur(input);

    expect(mutate).not.toHaveBeenCalled();
  });

  it("reverts an invalid entry on blur without saving", async () => {
    renderPage();

    const input = limitInput("Open Guild");
    fireEvent.change(input, { target: { value: "-3" } });
    fireEvent.blur(input);

    expect(mutate).not.toHaveBeenCalled();
    expect((input as HTMLInputElement).value).toBe(""); // snapped back to unlimited
  });
});
