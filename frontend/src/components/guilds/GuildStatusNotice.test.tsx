import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildGuild, guildCan } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { GuildEntry } from "@/hooks/useGuilds";

const state = vi.hoisted(() => ({
  billing: null as { url: string } | null,
  // The phone app, where nothing may be sold.
  native: false,
  support: { mode: "none", contact: null } as { mode: string; contact: string | null } | undefined,
}));
const askMock = vi.hoisted(() => vi.fn());
const openPortalMock = vi.hoisted(() => vi.fn());

vi.mock("@/hooks/useBillingPortal", () => ({
  useBillingPortal: () => ({
    billing: state.billing,
    canSell: state.billing != null && !state.native,
    openPortal: openPortalMock,
  }),
}));
vi.mock("@/hooks/useTickets", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/useTickets")>("@/hooks/useTickets");
  return {
    ...actual,
    useTicketAvailability: () => ({
      data: state.support && { support: state.support, moderation: state.support },
      isPending: false,
    }),
  };
});
vi.mock("@/api/generated/communities/communities", () => ({
  getReadCommunityPaymentIssueQueryKey: (id: number) => [
    `/api/v1/communities/${id}/billing/payment-issue`,
  ],
  readCommunityPaymentIssue: askMock,
}));

import { GuildStatusNotice, guildStatusNoticeApplies } from "./GuildStatusNotice";

const seatGuild = (overrides: Partial<GuildEntry> = {}): GuildEntry =>
  ({
    ...buildGuild({ id: 7, name: "Acme", role: "superadmin", status: "read_only" }),
    ...overrides,
  }) as GuildEntry;

describe("guildStatusNoticeApplies", () => {
  it("applies to the seat of a read-only guild", () => {
    expect(guildStatusNoticeApplies(seatGuild())).toBe(true);
  });

  it("does not apply to an active or suspended guild, an admin, or a grant", () => {
    expect(guildStatusNoticeApplies(seatGuild({ status: "active" }))).toBe(false);
    // A suspended guild is closed rather than noticed: its seat reaches nothing in it.
    expect(guildStatusNoticeApplies(seatGuild({ status: "suspended" }))).toBe(false);
    expect(guildStatusNoticeApplies(seatGuild({ role: "admin", can: guildCan("admin") }))).toBe(
      false
    );
    expect(guildStatusNoticeApplies(seatGuild({ accessType: "grant" }))).toBe(false);
  });
});

describe("GuildStatusNotice", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    state.native = false;
    state.billing = null;
    state.support = { mode: "none", contact: null };
    askMock.mockReset();
    openPortalMock.mockReset();
  });

  it("shows the default notice and asks nothing when no portal is configured", async () => {
    renderWithProviders(<GuildStatusNotice guild={seatGuild()} />);
    expect(await screen.findByText("Something is wrong")).toBeInTheDocument();
    expect(screen.getByText("Contact your platform operator.")).toBeInTheDocument();
    expect(askMock).not.toHaveBeenCalled();
  });

  it("offers to update the card when the payment was declined", async () => {
    state.billing = { url: "https://billing.example.com" };
    askMock.mockResolvedValue({ payment_failed: true });
    renderWithProviders(<GuildStatusNotice guild={seatGuild()} />);
    expect(await screen.findByText("The payment for Acme was declined")).toBeInTheDocument();
    expect(screen.queryByText("Something is wrong")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Update payment method" }));
    expect(openPortalMock).toHaveBeenCalledWith(7, "manage");
  });

  it("says the payment was declined in the app without offering to fix it there", async () => {
    state.billing = { url: "https://billing.example.com" };
    state.native = true;
    askMock.mockResolvedValue({ payment_failed: true });
    renderWithProviders(<GuildStatusNotice guild={seatGuild()} />);
    expect(await screen.findByText("The payment for Acme was declined")).toBeInTheDocument();
    expect(screen.getByText("Payment details can't be changed in the app.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Update payment method" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "OK" }));
    expect(openPortalMock).not.toHaveBeenCalled();
  });

  it("falls back to the default notice when the payment is not the problem", async () => {
    state.billing = { url: "https://billing.example.com" };
    askMock.mockResolvedValue({ payment_failed: false });
    renderWithProviders(<GuildStatusNotice guild={seatGuild()} />);
    expect(await screen.findByText("Something is wrong")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Update payment method" })).toBeNull();
  });

  it("falls back to the default notice when the question fails", async () => {
    state.billing = { url: "https://billing.example.com" };
    askMock.mockRejectedValue(new Error("unreachable"));
    renderWithProviders(<GuildStatusNotice guild={seatGuild()} />);
    expect(await screen.findByText("Something is wrong")).toBeInTheDocument();
  });

  it("offers a support request when help is on", async () => {
    state.support = { mode: "form", contact: null };
    renderWithProviders(<GuildStatusNotice guild={seatGuild()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Contact support" }));
    expect(await screen.findByLabelText("What is this about?")).toBeInTheDocument();
    expect(screen.queryByText("Something is wrong")).toBeNull();
  });

  it("offers the address the deployment gave when it takes no requests", async () => {
    state.support = { mode: "email", contact: "help@example.org" };
    renderWithProviders(<GuildStatusNotice guild={seatGuild()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Contact support" }));
    expect(await screen.findByText("help@example.org")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Write an email" })).toHaveAttribute(
      "href",
      "mailto:help@example.org"
    );
  });

  it("offers only OK when help is off", async () => {
    renderWithProviders(<GuildStatusNotice guild={seatGuild()} />);
    expect(await screen.findByRole("button", { name: "OK" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Contact support" })).toBeNull();
  });

  it("shows again in a new browser session", async () => {
    const first = renderWithProviders(<GuildStatusNotice guild={seatGuild()} />);
    await userEvent.click(await screen.findByRole("button", { name: "OK" }));
    first.unmount();
    window.sessionStorage.clear();
    renderWithProviders(<GuildStatusNotice guild={seatGuild()} />);
    expect(await screen.findByText("Something is wrong")).toBeInTheDocument();
  });

  it("shows once per guild in a session", async () => {
    const first = renderWithProviders(<GuildStatusNotice guild={seatGuild()} />);
    await userEvent.click(await screen.findByRole("button", { name: "OK" }));
    await waitFor(() => expect(screen.queryByText("Something is wrong")).toBeNull());
    first.unmount();

    renderWithProviders(<GuildStatusNotice guild={seatGuild()} />);
    expect(screen.queryByText("Something is wrong")).toBeNull();

    renderWithProviders(<GuildStatusNotice guild={seatGuild({ id: 8 })} />);
    expect(await screen.findByText("Something is wrong")).toBeInTheDocument();
  });
});
