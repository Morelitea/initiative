/**
 * The pill a phone navigates by.
 *
 * My Messages is the one destination here that can be waiting on you, so what
 * is worth asserting is that the count reaches somebody who cannot see a badge:
 * an `aria-label` wins over whatever is inside the button, so a number rendered
 * beside the icon is a number only some people get.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import { SidebarProvider } from "@/components/ui/sidebar";

const mocks = vi.hoisted(() => ({ waiting: vi.fn(), mobile: vi.fn(), notifications: vi.fn() }));

vi.mock("@/hooks/useMyMessages", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useMessagesWaiting: () => mocks.waiting(),
}));
vi.mock("@/hooks/use-mobile", () => ({ useIsMobile: () => mocks.mobile() }));
vi.mock("@/hooks/useNotifications", () => ({ useNotifications: () => mocks.notifications() }));

import { BottomNav } from "./BottomNav";

const setup = () =>
  renderPage(
    () => (
      <SidebarProvider>
        <BottomNav />
      </SidebarProvider>
    ),
    { initialRoute: "/" }
  );

beforeEach(() => {
  vi.clearAllMocks();
  mocks.waiting.mockReturnValue(0);
  mocks.mobile.mockReturnValue(true);
  mocks.notifications.mockReturnValue({ data: { unread_count: 0 } });
});

describe("the bottom bar", () => {
  it("goes to My Messages", async () => {
    const { router } = setup();

    await userEvent.click(await screen.findByRole("button", { name: "My Messages" }));

    expect(router.state.location.pathname).toBe("/messages");
  });

  it("says how much is waiting, in the name rather than only the badge", async () => {
    mocks.waiting.mockReturnValue(3);
    setup();

    expect(
      await screen.findByRole("button", { name: /My Messages, 3 waiting/ })
    ).toBeInTheDocument();
  });

  it("carries no mark when nothing is waiting", async () => {
    setup();

    const messages = await screen.findByRole("button", { name: "My Messages" });
    expect(messages).toHaveTextContent("");
  });

  it("is not offered where the pill is not", async () => {
    // The pill is the phone's navigation; a wide screen has the sidebar.
    mocks.mobile.mockReturnValue(false);
    setup();

    expect(screen.queryByRole("button", { name: /My Messages/ })).toBeNull();
  });
});
