/**
 * The home column, and the one route it drills into.
 *
 * Climbing out of the conversations is a look rather than a move — the thread
 * stays open behind it — so the address cannot be what puts the list back.
 * That makes "picking My Messages again drills back in" a thing only this
 * component can be asked about.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import { SidebarProvider } from "@/components/ui/sidebar";

const mocks = vi.hoisted(() => ({
  conversations: vi.fn(),
  unread: vi.fn(),
  messageRequests: vi.fn(),
  pending: vi.fn(),
}));

vi.mock("@/hooks/useMyMessages", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useConversations: () => mocks.conversations(),
  useUnreadMessages: () => mocks.unread(),
}));

vi.mock("@/hooks/useDirectMessages", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useMessageRequests: () => mocks.messageRequests(),
  usePendingMessageRequests: () => mocks.pending(),
  useAcceptMessageRequest: () => ({ mutate: vi.fn(), isPending: false }),
  useRemoveMessageRequest: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { HomeSidebarContent } from "./HomeSidebarContent";

const setup = (initialRoute: string) =>
  renderPage(
    () => (
      <SidebarProvider>
        <HomeSidebarContent />
      </SidebarProvider>
    ),
    { initialRoute }
  );

beforeEach(() => {
  vi.clearAllMocks();
  mocks.conversations.mockReturnValue({ data: { conversations: [] }, isLoading: false });
  mocks.unread.mockReturnValue({ data: new Map() });
  mocks.messageRequests.mockReturnValue({ data: { accepted: [], incoming: [], outgoing: [] } });
  mocks.pending.mockReturnValue(0);
});

describe("the home sidebar", () => {
  it("shows the navigation away from My Messages", async () => {
    setup("/");

    expect(await screen.findByText("My Contacts")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /back to navigation/i })).toBeNull();
  });

  it("drills into the conversations on My Messages", async () => {
    setup("/messages");

    expect(await screen.findByRole("button", { name: /back to navigation/i })).toBeInTheDocument();
    expect(screen.queryByText("My Contacts")).toBeNull();
  });

  it("drills back in when My Messages is picked again", async () => {
    // The route never changed, so nothing about the address can put the
    // conversations back — only picking the item again says to.
    setup("/messages");

    await userEvent.click(await screen.findByRole("button", { name: /back to navigation/i }));
    expect(await screen.findByText("My Contacts")).toBeInTheDocument();

    await userEvent.click(screen.getByText("My Messages"));

    expect(await screen.findByRole("button", { name: /back to navigation/i })).toBeInTheDocument();
  });
});
