import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildGuild, guildCan } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { GuildEntry } from "@/hooks/useGuilds";

const state = vi.hoisted(() => ({
  billing: null as { url: string } | null,
  support: { available: false } as { available: boolean } | undefined,
}));
const askMock = vi.hoisted(() => vi.fn());
const openPortalMock = vi.hoisted(() => vi.fn());

vi.mock("@/hooks/useBillingPortal", () => ({
  useBillingPortal: () => ({ billing: state.billing, openPortal: openPortalMock }),
}));
vi.mock("@/hooks/useSupport", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/useSupport")>("@/hooks/useSupport");
  return {
    ...actual,
    useSupportAvailability: () => ({ data: state.support, isPending: false }),
  };
});
vi.mock("@/api/generated/communities/communities", () => ({
  getReadGuildPaymentIssueApiV1CommunitiesGuildIdBillingPaymentIssueGetQueryKey: (id: number) => [
    `/api/v1/communities/${id}/billing/payment-issue`,
  ],
  readGuildPaymentIssueApiV1CommunitiesGuildIdBillingPaymentIssueGet: askMock,
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
    state.billing = null;
    state.support = { available: false };
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
    state.support = { available: true };
    renderWithProviders(<GuildStatusNotice guild={seatGuild()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Contact support" }));
    expect(await screen.findByLabelText("What is this about?")).toBeInTheDocument();
    expect(screen.queryByText("Something is wrong")).toBeNull();
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
