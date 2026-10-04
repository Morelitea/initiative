import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

let billingConfig: { url: string; operator_handoff: boolean; insights?: boolean } | null = {
  url: "https://billing.example.com",
  operator_handoff: true,
  insights: true,
};

vi.mock("@/hooks/useAppConfig", () => ({
  useAppConfig: () => ({ billing: billingConfig }),
}));

const mintHandoff = vi.fn();
vi.mock("@/api/generated/settings/settings", () => ({
  createBillingInsightsHandoff: () => mintHandoff(),
}));

import { OperatorDashboardBillingPage } from "./OperatorDashboardBillingPage";

const renderPage = (role: "operator" | "moderator" = "operator") =>
  renderWithProviders(<OperatorDashboardBillingPage />, {
    auth: { user: buildUser({ role }) },
  });

describe("OperatorDashboardBillingPage", () => {
  beforeEach(() => {
    mintHandoff.mockReset();
    billingConfig = {
      url: "https://billing.example.com",
      operator_handoff: true,
      insights: true,
    };
  });

  it("opens the insights page with a handoff that names no community", async () => {
    const location = { href: "" };
    const tab = { opener: {} as unknown, location, close: vi.fn() };
    const openSpy = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
    mintHandoff.mockResolvedValue({ handoff_token: "tok-9", expires_in_seconds: 60 });

    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /open billing insights/i }));

    const [path, fragment] = location.href.split("#");
    expect(path).toBe("https://billing.example.com/insights?lang=en");
    expect(fragment).toBe("insights_handoff=tok-9");
    expect(tab.opener).toBeNull();
    openSpy.mockRestore();
  });

  it("closes the blank tab when minting fails", async () => {
    const tab = { opener: {} as unknown, location: { href: "" }, close: vi.fn() };
    const openSpy = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
    mintHandoff.mockRejectedValue(new Error("nope"));

    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /open billing insights/i }));

    expect(tab.close).toHaveBeenCalled();
    openSpy.mockRestore();
  });

  it("offers no button when the deployment cannot open the page", async () => {
    billingConfig = { url: "https://billing.example.com", operator_handoff: true, insights: false };
    renderPage();

    expect(await screen.findByText(/no billing service to open/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /open billing insights/i })).toBeNull();
  });

  it("is closed to a tier without billing.insights", async () => {
    renderPage("moderator");

    expect(await screen.findByText(/for platform operators and owners/i)).toBeInTheDocument();
    expect(mintHandoff).not.toHaveBeenCalled();
  });
});
