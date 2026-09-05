/**
 * The list of people, in the column the navigation was in.
 *
 * What is worth proving here is the sorting and the answering — which section
 * somebody lands in, what a term leaves behind, and that a connection request
 * and a message request are told apart when they are answered, since they read
 * identically and are two different writes.
 */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildContactGrant } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";

const mocks = vi.hoisted(() => ({
  conversations: vi.fn(),
  unread: vi.fn(),
  favorites: vi.fn(),
  messageRequests: vi.fn(),
  connections: vi.fn(),
  acceptMessage: vi.fn(),
  removeMessage: vi.fn(),
  acceptConnection: vi.fn(),
  removeConnection: vi.fn(),
  settings: vi.fn(),
}));

// Finding somebody who is not on this list is its own surface, with its own
// test. Here it is a button that has to be reachable, nothing more.
vi.mock("@/components/messages/NewConversationDialog", () => ({
  NewConversationDialog: () => <button type="button">Start a conversation</button>,
}));

vi.mock("@/hooks/useMyMessages", () => ({
  useConversations: () => mocks.conversations(),
  useUnreadMessages: () => mocks.unread(),
}));

vi.mock("@/hooks/useContacts", () => ({
  useFavoriteContacts: () => mocks.favorites(),
  useToggleFavoriteContact: () => vi.fn(),
}));

vi.mock("@/hooks/useDirectMessages", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useMessageRequests: () => mocks.messageRequests(),
  useConnections: () => mocks.connections(),
  useDmSettings: () => mocks.settings(),
  useAcceptMessageRequest: () => ({ mutate: mocks.acceptMessage, isPending: false }),
  useRemoveMessageRequest: () => ({ mutate: mocks.removeMessage, isPending: false }),
  useAcceptConnection: () => ({ mutate: mocks.acceptConnection, isPending: false }),
  useRemoveConnection: () => ({ mutate: mocks.removeConnection, isPending: false }),
  useDmPermission: () => ({ data: undefined }),
  useDmPermissions: () => ({ data: { permissions: {} } }),
  useIgnoredAccounts: () => ({ data: { items: [], total: 0 } }),
  useIgnoreAccount: () => ({ mutate: vi.fn(), isPending: false }),
  useStopIgnoring: () => ({ mutate: vi.fn(), isPending: false }),
  useRequestConnection: () => ({ mutate: vi.fn(), isPending: false }),
  useRequestMessage: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { ConversationList } from "./ConversationList";

const ADA = buildContactGrant({ user_id: 1, username: "ada" });
const GRACE = buildContactGrant({ user_id: 2, username: "grace" });

const noGrants = { accepted: [], incoming: [], outgoing: [] };

const show = () => renderPage(() => <ConversationList />, { initialRoute: "/messages" });

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  mocks.conversations.mockReturnValue({ data: { conversations: [] }, isLoading: false });
  mocks.unread.mockReturnValue({ data: new Map<string, number>() });
  mocks.favorites.mockReturnValue({ data: { items: [] } });
  mocks.messageRequests.mockReturnValue({ data: { ...noGrants, accepted: [ADA, GRACE] } });
  mocks.connections.mockReturnValue({ data: noGrants });
  mocks.settings.mockReturnValue({
    data: { dm_policy: "community", communities: [], age_confirmed_at: "2020-01-01T00:00:00Z" },
  });
});

describe("ConversationList", () => {
  it("reads anybody with something waiting at the top, whatever else they are", async () => {
    // Starred, so without the unread they would be under Favorites.
    mocks.favorites.mockReturnValue({ data: { items: [{ id: 1 }] } });
    mocks.conversations.mockReturnValue({
      data: { conversations: [{ id: "c1", other_user_id: 1 }] },
      isLoading: false,
    });
    mocks.unread.mockReturnValue({ data: new Map([["c1", 3]]) });
    show();

    const headings = await screen.findAllByRole("button", { name: /Unread|Favorites|Messages/ });
    expect(headings[0]).toHaveTextContent(/Unread/);
    expect(headings[0]).toHaveTextContent("1");
    // And not left behind under the section they would otherwise sort into.
    expect(screen.queryByRole("button", { name: /Favorites/ })).not.toBeInTheDocument();
  });

  it("narrows the list to a handle, without asking the server for anything", async () => {
    show();
    expect(await screen.findByText("ada#1234")).toBeVisible();

    await userEvent.type(screen.getByRole("textbox", { name: /Search conversations/i }), "grace");

    expect(screen.queryByText("ada#1234")).not.toBeInTheDocument();
    expect(screen.getByText("grace#1234")).toBeVisible();
  });

  it("says so when a term matches nobody", async () => {
    show();
    await userEvent.type(
      await screen.findByRole("textbox", { name: /Search conversations/i }),
      "nobody"
    );

    expect(screen.getByText("Nobody matches.")).toBeVisible();
  });

  it("answers a connection request with the connection write, not the message one", async () => {
    mocks.messageRequests.mockReturnValue({ data: noGrants });
    mocks.connections.mockReturnValue({
      data: { ...noGrants, incoming: [buildContactGrant({ user_id: 9, username: "alan" })] },
    });
    show();

    expect(await screen.findByText("They want to connect.")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Accept" }));

    expect(mocks.acceptConnection).toHaveBeenCalledWith({ userId: 9 });
    expect(mocks.acceptMessage).not.toHaveBeenCalled();
  });

  it("keeps a message request answerable beside it", async () => {
    mocks.messageRequests.mockReturnValue({
      data: { ...noGrants, incoming: [buildContactGrant({ user_id: 8, username: "edsger" })] },
    });
    show();

    expect(await screen.findByText("They want to start a conversation.")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Accept" }));

    expect(mocks.acceptMessage).toHaveBeenCalledWith({ userId: 8 });
  });

  it("carries what you asked for, so a sent request does not look like it never happened", async () => {
    mocks.connections.mockReturnValue({
      data: {
        ...noGrants,
        outgoing: [buildContactGrant({ user_id: 5, username: "hedy", outgoing: true })],
      },
    });
    show();

    expect(await screen.findByText(/You asked to connect/)).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(mocks.removeConnection).toHaveBeenCalledWith({ userId: 5 });
  });

  it("puts what else can be done about somebody on their own row", async () => {
    show();
    const row = (await screen.findByText("ada#1234")).closest("li") as HTMLElement;

    expect(within(row).getByRole("button", { name: /Actions for ada/i })).toBeInTheDocument();
  });

  it("explains an empty list by the setting that emptied it", async () => {
    mocks.messageRequests.mockReturnValue({ data: noGrants });
    mocks.settings.mockReturnValue({
      data: { dm_policy: "private", communities: [], age_confirmed_at: "2020-01-01T00:00:00Z" },
    });
    show();

    // Not "nobody yet", which would read as an absence of people rather than
    // as the reader's own choice.
    expect(await screen.findByText(/You're set to Private/)).toBeVisible();
    expect(screen.queryByText(/Nobody yet/)).toBeNull();
  });

  it("says the age question is what is holding it back, and where to answer it", async () => {
    mocks.messageRequests.mockReturnValue({ data: noGrants });
    mocks.settings.mockReturnValue({
      data: { dm_policy: "community", communities: [], age_confirmed_at: null },
    });
    show();

    expect(await screen.findByText(/aged 13 and over/)).toBeVisible();
    expect(screen.getByRole("link", { name: "Privacy settings" })).toHaveAttribute(
      "href",
      "/profile/privacy"
    );
  });

  it("guesses nothing before the settings arrive", async () => {
    // Absent, they read as an account that has answered nothing -- which is
    // the one thing that must never be shown to somebody who has.
    mocks.messageRequests.mockReturnValue({ data: noGrants });
    mocks.settings.mockReturnValue({ data: undefined });
    show();

    expect(await screen.findByText(/Nobody yet/)).toBeVisible();
    expect(screen.queryByText(/aged 13 and over/)).toBeNull();
  });

  it("offers a way to find somebody who is not on it at all", async () => {
    mocks.messageRequests.mockReturnValue({ data: noGrants });
    show();

    expect(
      await screen.findByText(
        "Nobody yet. A conversation opens once a message request is accepted."
      )
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Start a conversation" })).toBeVisible();
  });
});
