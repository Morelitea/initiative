import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildGuild, guildCan } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { GuildBillingSummaryRead } from "@/api/generated/initiativeAPI.schemas";

// Mutable state the mocked hooks read, so each test can vary billing config,
// the active guild, and what the summary route answered.
const state = vi.hoisted(() => ({
  guild: null as ReturnType<typeof Object> | null,
  billing: null as { url: string } | null,
  summary: undefined as GuildBillingSummaryRead | undefined,
  summaryError: false,
}));

vi.mock("@/hooks/useGuilds", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/useGuilds")>("@/hooks/useGuilds");
  // Keep GuildContext (the render helper's provider imports it); override the hook.
  return { ...actual, useGuilds: () => ({ activeGuild: state.guild }) };
});
vi.mock("@/hooks/useAppConfig", () => ({
  useAppConfig: () => ({ billing: state.billing }),
}));
const mintMock = vi.hoisted(() => vi.fn());
vi.mock("@/api/generated/communities/communities", () => ({
  createGuildBillingHandoffApiV1CommunitiesGuildIdBillingHandoffPost: mintMock,
}));
// Who is asked, and when, is the hook's (useGuildBillingSummary.test.tsx);
// this is what the panel makes of the answer.
vi.mock("@/hooks/useGuildBillingSummary", () => ({
  useGuildBillingSummary: () => ({ data: state.summary, isError: state.summaryError }),
}));

import { GuildBillingPanel } from "./GuildBillingPanel";

const EMPTY: GuildBillingSummaryRead = {
  available: true,
  tier_name: null,
  trial_ends_on: null,
  renews_on: null,
  next_charge: null,
  scheduled_change: null,
  payment_failed: false,
};

/** A local calendar day `days` from today, as the API sends a DATE. */
const dayFromToday = (days: number): string => {
  const now = new Date();
  const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() + days);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};

const longDate = (value: string): string => {
  const [y, m, d] = value.split("-").map(Number);
  return new Intl.DateTimeFormat("en", { dateStyle: "long" }).format(new Date(y, m - 1, d));
};

describe("GuildBillingPanel", () => {
  beforeEach(() => {
    state.guild = buildGuild({ id: 42, role: "superadmin", tier_name: "Tin" });
    state.billing = { url: "https://billing.example.com" };
    state.summary = { ...EMPTY };
    state.summaryError = false;
    mintMock.mockReset();
  });

  it("renders nothing without a billing portal", () => {
    state.billing = null;
    const { container } = renderWithProviders(<GuildBillingPanel />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows support the plan when they hold the seat with write access", () => {
    // A superadmin settings grant beside a read_write content grant: what
    // support does with it happens in the billing portal, under its controls.
    state.guild = {
      ...buildGuild({
        id: 42,
        role: "superadmin",
        can: guildCan("superadmin", { configure: true }),
      }),
      accessType: "grant",
      grantSettingsLevel: "superadmin",
    };
    renderWithProviders(<GuildBillingPanel />);
    expect(screen.getByText("Plan")).toBeInTheDocument();
  });

  it("renders nothing for support whose grant only reads", () => {
    state.guild = {
      ...buildGuild({
        id: 42,
        role: "superadmin",
        can: guildCan("superadmin", { configure: false }),
      }),
      accessType: "grant",
      grantSettingsLevel: "superadmin",
    };
    const { container } = renderWithProviders(<GuildBillingPanel />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing for a seat whose session only reads", () => {
    state.guild = buildGuild({
      id: 42,
      role: "superadmin",
      can: guildCan("superadmin", { configure: false }),
    });
    const { container } = renderWithProviders(<GuildBillingPanel />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing for an ordinary admin", () => {
    state.guild = buildGuild({ id: 42, role: "admin" });
    const { container } = renderWithProviders(<GuildBillingPanel />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows just the plan name on a free plan", () => {
    renderWithProviders(<GuildBillingPanel />);
    expect(screen.getByText("Tin")).toBeInTheDocument();
    expect(screen.queryByText(/Renews|Trial|Ends|Payment failed/)).not.toBeInTheDocument();
    expect(screen.getByText("Manage billing")).toBeInTheDocument();
    expect(
      screen.getByText(/read-only for 30 days so you can export it, then put on hold and deleted/)
    ).toBeInTheDocument();
    expect(screen.getByText(/Change your plan, payment method or cancel/)).toBeInTheDocument();
  });

  it("counts down a running trial", () => {
    const end = dayFromToday(3);
    state.summary = { ...EMPTY, tier_name: "Gold", trial_ends_on: end };
    renderWithProviders(<GuildBillingPanel />);
    expect(screen.getByText("Gold")).toBeInTheDocument();
    expect(screen.getByText("Trial · 3 days left")).toBeInTheDocument();
    expect(
      screen.getByText(`Trial ends ${longDate(end)}. Subscribe before then to keep editing.`)
    ).toBeInTheDocument();
  });

  it("says so on a trial's last day", () => {
    state.summary = { ...EMPTY, trial_ends_on: dayFromToday(0) };
    renderWithProviders(<GuildBillingPanel />);
    expect(screen.getByText("Trial · last day")).toBeInTheDocument();
  });

  it("shows the renewal date and amount in the currency's own units", () => {
    const renews = dayFromToday(20);
    state.summary = {
      ...EMPTY,
      tier_name: "Gold",
      renews_on: renews,
      next_charge: { total: 1250, currency: "USD" },
    };
    renderWithProviders(<GuildBillingPanel />);
    expect(screen.getByText(`Renews ${longDate(renews)} · $12.50`)).toBeInTheDocument();
  });

  it("reads minor units by the currency's fraction digits", () => {
    const renews = dayFromToday(20);
    state.summary = { ...EMPTY, renews_on: renews, next_charge: { total: 1200, currency: "JPY" } };
    renderWithProviders(<GuildBillingPanel />);
    expect(screen.getByText(`Renews ${longDate(renews)} · ¥1,200`)).toBeInTheDocument();
  });

  it("shows a scheduled cancelation over the renewal", () => {
    const ends = dayFromToday(20);
    state.summary = {
      ...EMPTY,
      renews_on: ends,
      next_charge: { total: 1250, currency: "USD" },
      scheduled_change: { action: "cancel", on: ends },
    };
    renderWithProviders(<GuildBillingPanel />);
    expect(screen.getByText(`Ends ${longDate(ends)}`)).toBeInTheDocument();
    expect(
      screen.getByText(
        `Your plan ends on ${longDate(ends)}. After that the community is read-only for 30 days, then put on hold.`
      )
    ).toBeInTheDocument();
    expect(screen.queryByText(/Renews/)).not.toBeInTheDocument();
  });

  it("puts a failed payment first and sends the seat to fix it", async () => {
    state.summary = {
      ...EMPTY,
      renews_on: dayFromToday(20),
      next_charge: { total: 1250, currency: "USD" },
      payment_failed: true,
    };
    mintMock.mockResolvedValue({ handoff_token: "TOK", expires_in_seconds: 60 });
    const tab = { location: { href: "" }, opener: {} as unknown };
    const openSpy = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);

    renderWithProviders(<GuildBillingPanel />);
    expect(screen.getByText("Payment failed")).toBeInTheDocument();
    expect(screen.getByText(/read-only 14 days after the payment failed/)).toBeInTheDocument();
    expect(screen.queryByText(/Renews/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByText("Update payment method"));

    expect(mintMock).toHaveBeenCalledWith(42);
    await waitFor(() =>
      expect(tab.location.href).toBe(
        "https://billing.example.com/manage?guild=42&lang=en#handoff=TOK"
      )
    );
    openSpy.mockRestore();
  });

  it("says billing is unavailable, and still offers the portal", () => {
    state.summary = { ...EMPTY, available: false };
    renderWithProviders(<GuildBillingPanel />);
    expect(screen.getByText("Billing details are unavailable right now.")).toBeInTheDocument();
    // The plan name falls back to what the guild itself carries.
    expect(screen.getByText("Tin")).toBeInTheDocument();
    expect(screen.getByText("Manage billing")).toBeInTheDocument();
  });

  it("treats a refused summary as unavailable", () => {
    state.summary = undefined;
    state.summaryError = true;
    renderWithProviders(<GuildBillingPanel />);
    expect(screen.getByText("Billing details are unavailable right now.")).toBeInTheDocument();
  });

  it("falls back to the anonymous link if the mint fails", async () => {
    mintMock.mockRejectedValue(new Error("nope"));
    const tab = { location: { href: "" }, opener: {} as unknown };
    const openSpy = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);

    renderWithProviders(<GuildBillingPanel />);
    await userEvent.click(screen.getByText("Upgrade"));

    await waitFor(() =>
      expect(tab.location.href).toBe("https://billing.example.com/upgrade?guild=42&lang=en")
    );
    openSpy.mockRestore();
  });
});
