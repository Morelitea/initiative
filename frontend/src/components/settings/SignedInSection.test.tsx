/**
 * The one list, built from two credentials.
 *
 * What is worth pinning here is the merge: browser sessions and signed-in
 * phones arrive from different endpoints in different shapes, and the person
 * reading the page is owed one ordered list where the row they are sitting at
 * is obvious and is not offered a button that would sign them out of the page
 * they are on.
 */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";

import { SignedInSection } from "./SignedInSection";

const mocks = vi.hoisted(() => ({
  sessions: vi.fn(),
  devices: vi.fn(),
  revokeSession: vi.fn(),
  revokeDevice: vi.fn(),
  revokeOthers: vi.fn(),
}));

vi.mock("@/lib/chesterToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/hooks/useSecurity", () => ({
  useMySessions: () => mocks.sessions(),
  useDeviceTokens: () => mocks.devices(),
  useRevokeSession: () => ({ mutate: mocks.revokeSession, isPending: false }),
  useRevokeDeviceToken: () => ({ mutate: mocks.revokeDevice, isPending: false }),
  useRevokeOtherSessions: () => ({ mutate: mocks.revokeOthers, isPending: false }),
}));

const HOUR = 3_600_000;
const ago = (ms: number) => new Date(Date.now() - ms).toISOString();

const thisBrowser = {
  id: "11111111-1111-1111-1111-111111111111",
  label: "Chrome on macOS",
  kind: "desktop" as const,
  ip: "192.168.1.14",
  started_at: ago(30 * 24 * HOUR),
  last_used_at: ago(60_000),
  is_current: true,
};

const otherBrowser = {
  id: "22222222-2222-2222-2222-222222222222",
  label: "Firefox on Windows",
  kind: "desktop" as const,
  ip: "86.20.4.11",
  started_at: ago(5 * 24 * HOUR),
  last_used_at: ago(3 * HOUR),
  is_current: false,
};

const phone = { id: 7, device_name: "Lee's iPhone", created_at: ago(10 * 24 * HOUR) };

const loaded = <T,>(data: T) => ({ data, isLoading: false, isError: false });

const rows = () => screen.getAllByRole("button", { name: /sign out$/i });

beforeEach(() => {
  vi.clearAllMocks();
  mocks.sessions.mockReturnValue(loaded([thisBrowser, otherBrowser]));
  mocks.devices.mockReturnValue(loaded([phone]));
});

describe("SignedInSection", () => {
  it("shows browsers and phones in one list", () => {
    renderWithProviders(<SignedInSection />);

    expect(screen.getByText("Chrome on macOS")).toBeInTheDocument();
    expect(screen.getByText("Firefox on Windows")).toBeInTheDocument();
    expect(screen.getByText("Lee's iPhone")).toBeInTheDocument();
  });

  it("marks the session doing the reading and offers it no way out", () => {
    // Signing the current session out is what the sign-out button is for; a
    // row that did it here would be a second, stranger way to do the same.
    renderWithProviders(<SignedInSection />);

    const current = screen.getByText("Chrome on macOS").closest("div.rounded-lg");
    expect(current).not.toBeNull();
    expect(within(current as HTMLElement).getByText("This device")).toBeInTheDocument();
    expect(within(current as HTMLElement).queryByRole("button", { name: /sign out/i })).toBeNull();

    // Every other row keeps one.
    expect(rows()).toHaveLength(2);
  });

  it("puts the current session first, then the most recently active", () => {
    renderWithProviders(<SignedInSection />);

    const labels = screen
      .getAllByText(/Chrome on macOS|Firefox on Windows|Lee's iPhone/)
      .map((node) => node.textContent?.replace("This device", "").trim());
    expect(labels).toEqual(["Chrome on macOS", "Firefox on Windows", "Lee's iPhone"]);
  });

  it("ends a browser session by its id", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SignedInSection />);

    const other = screen.getByText("Firefox on Windows").closest("div.rounded-lg");
    await user.click(within(other as HTMLElement).getByRole("button", { name: /sign out/i }));
    await user.click(screen.getByRole("button", { name: "Sign out" }));

    expect(mocks.revokeSession).toHaveBeenCalledWith(otherBrowser.id);
    expect(mocks.revokeDevice).not.toHaveBeenCalled();
  });

  it("ends a phone through the other credential", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SignedInSection />);

    const row = screen.getByText("Lee's iPhone").closest("div.rounded-lg");
    await user.click(within(row as HTMLElement).getByRole("button", { name: /sign out/i }));
    await user.click(screen.getByRole("button", { name: "Sign out" }));

    expect(mocks.revokeDevice).toHaveBeenCalledWith(phone.id);
    expect(mocks.revokeSession).not.toHaveBeenCalled();
  });

  it("offers the sweep only when there is somewhere else to sweep", () => {
    mocks.sessions.mockReturnValue(loaded([thisBrowser]));
    mocks.devices.mockReturnValue(loaded([]));
    renderWithProviders(<SignedInSection />);

    expect(screen.queryByRole("button", { name: /everywhere else/i })).toBeNull();
  });

  it("sweeps everywhere else on confirmation", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SignedInSection />);

    await user.click(screen.getByRole("button", { name: "Sign out everywhere else" }));
    // The dialog names how many go, so the count covers both credentials.
    expect(screen.getByText(/ends all 2 other sessions/i)).toBeInTheDocument();

    const dialog = screen.getByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Sign out everywhere else" }));
    expect(mocks.revokeOthers).toHaveBeenCalled();
  });

  it("says so when the account is signed in nowhere else", () => {
    mocks.sessions.mockReturnValue(loaded([]));
    mocks.devices.mockReturnValue(loaded([]));
    renderWithProviders(<SignedInSection />);

    expect(screen.getByText("Nowhere else")).toBeInTheDocument();
  });
});
