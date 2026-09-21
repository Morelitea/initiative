import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import { removeItem } from "@/lib/storage";

const mocks = vi.hoisted(() => ({
  config: {
    captcha: null as { provider: string; site_key: string } | null,
    cookieNoticeEnabled: true,
    isLoading: false,
  },
  legal: { enabled: false, documents: [] as { slug: string; title: string }[] },
}));

vi.mock("@/hooks/useAppConfig", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useAppConfig")>()),
  useAppConfig: () => mocks.config,
}));

vi.mock("@/hooks/useLegalDocuments", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useLegalDocuments")>()),
  useLegalIndex: () => ({ ...mocks.legal, required: [], isLoading: false }),
}));

import { CookieNotice } from "./CookieNotice";

const notice = () => screen.queryByRole("region", { name: /cookies and browser storage/i });

describe("CookieNotice", () => {
  beforeEach(() => {
    removeItem("cookie-notice-seen");
    mocks.config = { captcha: null, cookieNoticeEnabled: true, isLoading: false };
    mocks.legal = { enabled: false, documents: [] };
  });

  it("greets somebody arriving for the first time", () => {
    renderWithProviders(<CookieNotice />);

    expect(notice()).toBeInTheDocument();
    expect(screen.getByText(/no advertising, no analytics/i)).toBeInTheDocument();
  });

  it("offers one way out, and no choice to make — there is nothing optional to reject", async () => {
    const user = userEvent.setup();
    renderWithProviders(<CookieNotice />);

    expect(screen.getAllByRole("button")).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: /got it/i }));

    expect(notice()).not.toBeInTheDocument();
  });

  it("stays gone on the next visit", async () => {
    const user = userEvent.setup();
    const first = renderWithProviders(<CookieNotice />);
    await user.click(screen.getByRole("button", { name: /got it/i }));
    first.unmount();

    renderWithProviders(<CookieNotice />);

    expect(notice()).not.toBeInTheDocument();
  });

  it("says nothing where the deployment has not asked it to", () => {
    mocks.config = { ...mocks.config, cookieNoticeEnabled: false };

    renderWithProviders(<CookieNotice />);

    expect(notice()).not.toBeInTheDocument();
  });

  it("waits for the deployment's answer rather than appearing and then vanishing", () => {
    mocks.config = { ...mocks.config, isLoading: true };

    renderWithProviders(<CookieNotice />);

    expect(notice()).not.toBeInTheDocument();
  });

  it("is not shown in the installed app, which landed on no site", () => {
    renderWithProviders(<CookieNotice />, { server: { isNativePlatform: true } });

    expect(notice()).not.toBeInTheDocument();
  });

  it("names the spam check the deployment put in front of sign-up", () => {
    mocks.config = {
      ...mocks.config,
      captcha: { provider: "turnstile", site_key: "site-key" },
    };

    renderWithProviders(<CookieNotice />);

    expect(screen.getByText(/Cloudflare Turnstile/)).toBeInTheDocument();
  });

  it("claims no third party where the deployment configured none", () => {
    renderWithProviders(<CookieNotice />);

    expect(screen.queryByText(/spam check/i)).not.toBeInTheDocument();
  });

  it("points at the deployment's own privacy policy where it has one", () => {
    mocks.legal = { enabled: true, documents: [{ slug: "privacy", title: "Privacy Policy" }] };

    renderWithProviders(<CookieNotice />);

    expect(screen.getByRole("link", { name: /privacy policy/i })).toHaveAttribute(
      "href",
      "/legal/privacy"
    );
  });

  it("offers no policy link where the deployment has no policy of its own", () => {
    renderWithProviders(<CookieNotice />);

    expect(screen.queryByRole("link", { name: /privacy policy/i })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /what's kept/i })).toBeInTheDocument();
  });
});
