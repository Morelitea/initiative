/**
 * My Messages, through the router the app ships.
 *
 * The page is only useful if it is reachable: the generated route tree has to
 * serve `/messages` — outside the community tree, because a direct message is
 * not a community's business — and load the page from its own chunk. A test
 * that mounts the component directly proves neither.
 *
 * The crypto itself is proved in `src/crypto/ratchet.test.ts`, against the real
 * ratchet. What is worth proving here is what the page does with it: that a
 * device is registered before anything is read, that a thread renders from this
 * device's own store rather than from an endpoint, and that sending goes
 * through the ratchet rather than posting a body.
 */
import { createRouter } from "@tanstack/react-router";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { RecipientHasNoDeviceError } from "@/crypto/messaging";
import { routeTree } from "@/routeTree.gen";

import { renderPage } from "./helpers/render";

const MESSAGES_ROUTE_ID = "/_serverRequired/_authenticated/messages";

const mocks = vi.hoisted(() => ({
  ensureDevice: vi.fn(),
  collect: vi.fn(),
  sendText: vi.fn(),
  logGet: vi.fn(),
  conversations: vi.fn(),
  createConversation: vi.fn(),
  messageRequests: vi.fn(),
}));

// The ratchet is exercised for real in src/crypto/ratchet.test.ts. Here it is
// the seam the page talks to, so the page's own behaviour is what is on trial.
vi.mock("@/crypto/messaging", async (importOriginal) => ({
  // The error class is real: the page tells one kind of failure from another by
  // identity, so a stand-in would prove nothing.
  RecipientHasNoDeviceError: (await importOriginal<Record<string, unknown>>())
    .RecipientHasNoDeviceError,
  ensureDevice: () => mocks.ensureDevice(),
  collect: () => mocks.collect(),
  sendText: (conversationId: string, otherUserId: number, body: string) =>
    mocks.sendText(conversationId, otherUserId, body),
  messageLog: { get: (id: string) => mocks.logGet(id) },
}));

vi.mock("@/api/generated/direct-messages/direct-messages", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  listConversationsApiV1MeDmConversationsGet: () => mocks.conversations(),
  createConversationApiV1MeDmConversationsPost: (body: { user_id: number }) =>
    mocks.createConversation(body),
}));

vi.mock("@/hooks/useDirectMessages", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useMessageRequests: () => mocks.messageRequests(),
}));

const router = createRouter({ routeTree });

// The page refuses outright where there are no web workers, because the ratchet
// cannot run there. jsdom has none, so one stands in — nothing here calls it,
// since the crypto seam is mocked below.
const noWorker = globalThis.Worker === undefined;
beforeAll(() => {
  if (noWorker) globalThis.Worker = class {} as unknown as typeof Worker;
});
afterAll(() => {
  if (noWorker) Reflect.deleteProperty(globalThis, "Worker");
});

const grant = (userId: number, username: string) => ({
  user_id: userId,
  username,
  discriminator: 1234,
  avatar_url: null,
  status: "active" as const,
  presence: "offline" as const,
  state: "accepted",
  outgoing: false,
  created_at: "2026-09-01T00:00:00Z",
  responded_at: "2026-09-01T00:00:00Z",
});

const messagesPage = async () => {
  const route = router.routesById[MESSAGES_ROUTE_ID];
  const Page = route.options.component as React.ComponentType & {
    preload?: () => Promise<unknown>;
  };
  // The dynamic import the route is declared with: a moved page or a renamed
  // export fails here rather than at a click.
  await Page.preload?.();
  return Page;
};

const renderMessages = async () => {
  const Page = await messagesPage();
  return renderPage(Page, { initialRoute: "/messages" });
};

beforeEach(() => {
  vi.clearAllMocks();
  mocks.ensureDevice.mockResolvedValue("device-1");
  mocks.collect.mockResolvedValue([]);
  mocks.sendText.mockResolvedValue({ id: "1", body: "hi", at: "", mine: true });
  mocks.logGet.mockResolvedValue([]);
  mocks.conversations.mockResolvedValue({ conversations: [] });
  mocks.messageRequests.mockReturnValue({ data: { accepted: [], incoming: [], outgoing: [] } });
});

describe("My Messages", () => {
  it("is reachable at /messages and registers this device before reading", async () => {
    await renderMessages();

    expect(await screen.findByRole("heading", { name: /my messages/i })).toBeInTheDocument();
    await waitFor(() => expect(mocks.ensureDevice).toHaveBeenCalled());
  });

  it("says so when there is nobody to message yet", async () => {
    await renderMessages();

    expect(await screen.findByText(/nobody yet/i)).toBeInTheDocument();
  });

  it("renders a thread out of this device's own store", async () => {
    mocks.conversations.mockResolvedValue({
      conversations: [{ id: "conv-1", other_user_id: 7, created_at: "2026-09-01T00:00:00Z" }],
    });
    mocks.messageRequests.mockReturnValue({
      data: { accepted: [grant(7, "alex")], incoming: [], outgoing: [] },
    });
    mocks.logGet.mockResolvedValue([
      { id: "m1", body: "only this device has this", at: "", mine: false },
    ]);

    await renderMessages();
    await userEvent.click(await screen.findByRole("button", { name: /alex#1234/ }));

    expect(await screen.findByText("only this device has this")).toBeInTheDocument();
    expect(mocks.logGet).toHaveBeenCalledWith("conv-1");
  });

  it("collects again when a dm frame invalidates the mailbox", async () => {
    // A content-free frame is the only thing that says a message arrived, so
    // the collection has to be something invalidation can re-run.
    const { queryClient } = await renderMessages();
    await waitFor(() => expect(mocks.collect).toHaveBeenCalledTimes(1));

    // What the `dm` frame does: invalidate everything under ["dm"].
    await queryClient.invalidateQueries({ queryKey: ["dm"] });

    await waitFor(() => expect(mocks.collect).toHaveBeenCalledTimes(2));
  });

  it("does not carry a half-written message into another conversation", async () => {
    // A composer keeps a draft. If the thread is not remounted per conversation
    // the draft follows the switch, and the next Send addresses somebody else.
    mocks.conversations.mockResolvedValue({
      conversations: [
        { id: "conv-1", other_user_id: 7, created_at: "2026-09-01T00:00:00Z" },
        { id: "conv-2", other_user_id: 8, created_at: "2026-09-01T00:00:00Z" },
      ],
    });
    mocks.messageRequests.mockReturnValue({
      data: { accepted: [grant(7, "alex"), grant(8, "sam")], incoming: [], outgoing: [] },
    });

    await renderMessages();
    await userEvent.click(await screen.findByRole("button", { name: /alex#1234/ }));
    await userEvent.type(await screen.findByLabelText(/write a message/i), "meant for alex");
    await userEvent.click(await screen.findByRole("button", { name: /sam#1234/ }));

    expect(await screen.findByLabelText(/write a message/i)).toHaveValue("");
  });

  it("says an account has no device rather than reporting a plain failure", async () => {
    mocks.conversations.mockResolvedValue({
      conversations: [{ id: "conv-1", other_user_id: 7, created_at: "2026-09-01T00:00:00Z" }],
    });
    mocks.messageRequests.mockReturnValue({
      data: { accepted: [grant(7, "alex")], incoming: [], outgoing: [] },
    });
    mocks.sendText.mockRejectedValue(new RecipientHasNoDeviceError());

    await renderMessages();
    await userEvent.click(await screen.findByRole("button", { name: /alex#1234/ }));
    await userEvent.type(await screen.findByLabelText(/write a message/i), "hello");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(await screen.findByText(/has not set up encrypted messages/i)).toBeInTheDocument();
    // And the text comes back, because the composer was the only copy of it.
    expect(screen.getByLabelText(/write a message/i)).toHaveValue("hello");
  });

  it("sends through the ratchet rather than posting a body", async () => {
    mocks.conversations.mockResolvedValue({
      conversations: [{ id: "conv-1", other_user_id: 7, created_at: "2026-09-01T00:00:00Z" }],
    });
    mocks.messageRequests.mockReturnValue({
      data: { accepted: [grant(7, "alex")], incoming: [], outgoing: [] },
    });

    await renderMessages();
    await userEvent.click(await screen.findByRole("button", { name: /alex#1234/ }));
    await userEvent.type(await screen.findByLabelText(/write a message/i), "hello");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));

    await waitFor(() => expect(mocks.sendText).toHaveBeenCalledWith("conv-1", 7, "hello"));
  });
});
