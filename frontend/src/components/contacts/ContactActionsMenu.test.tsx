/**
 * What one person can do about another, and when.
 *
 * The menu is the only caller the ignore write has: before it, ignoring an
 * account meant already knowing its exact handle and opening Settings. So the
 * assertions here are mostly about an item being *offered* at the moment
 * somebody would reach for it.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildContactGrant, buildIgnoredAccount } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";

const mocks = vi.hoisted(() => ({
  permission: vi.fn(),
  connections: vi.fn(),
  ignored: vi.fn(),
  requestConnection: vi.fn(),
  requestMessage: vi.fn(),
  removeConnection: vi.fn(),
  ignore: vi.fn(),
  stopIgnoring: vi.fn(),
}));

vi.mock("@/hooks/useDirectMessages", () => ({
  useDmPermission: () => mocks.permission(),
  useConnections: () => mocks.connections(),
  useIgnoredAccounts: () => mocks.ignored(),
  useRequestConnection: () => ({ mutate: mocks.requestConnection, isPending: false }),
  useRequestMessage: () => ({ mutate: mocks.requestMessage, isPending: false }),
  useRemoveConnection: () => ({ mutate: mocks.removeConnection, isPending: false }),
  useIgnoreAccount: () => ({ mutate: mocks.ignore, isPending: false }),
  useStopIgnoring: () => ({ mutate: mocks.stopIgnoring, isPending: false }),
}));

import { ContactActionsMenu } from "./ContactActionsMenu";

const ADA = { id: 7, username: "ada", discriminator: 1234 };

// Through a router: one of the items is a link to the person's profile, and a
// `Link` outside a router does not render at all.
const open = async () => {
  renderPage(() => <ContactActionsMenu user={ADA} />);
  await userEvent.click(await screen.findByRole("button", { name: /Actions for ada/i }));
};

beforeEach(() => {
  vi.clearAllMocks();
  mocks.permission.mockReturnValue({ data: { permission: "denied" } });
  mocks.connections.mockReturnValue({ data: { accepted: [], incoming: [], outgoing: [] } });
  mocks.ignored.mockReturnValue({ data: { items: [], total: 0 } });
});

describe("ContactActionsMenu", () => {
  it("offers ignoring somebody where you met them", async () => {
    await open();
    await userEvent.click(await screen.findByRole("menuitem", { name: "Ignore" }));

    expect(mocks.ignore).toHaveBeenCalledWith({ userId: 7 });
  });

  it("offers to stop, once they are on the list", async () => {
    mocks.ignored.mockReturnValue({
      data: { items: [buildIgnoredAccount({ user_id: 7 })], total: 1 },
    });
    await open();

    expect(await screen.findByRole("menuitem", { name: "Stop ignoring" })).toBeVisible();
    expect(screen.queryByRole("menuitem", { name: "Ignore" })).toBeNull();
  });

  it("addresses a connection by handle, which is what reaches a private account", async () => {
    await open();
    await userEvent.click(await screen.findByRole("menuitem", { name: "Connect" }));

    expect(mocks.requestConnection).toHaveBeenCalledWith(
      { data: { username: "ada", discriminator: 1234 } },
      expect.anything()
    );
  });

  it("offers the conversation itself where there is one", async () => {
    // No "view profile" here: both places this menu appears are already the
    // person. What it offers instead is where the two of you talk.
    mocks.permission.mockReturnValue({ data: { permission: "open" } });
    await open();

    expect(screen.getByRole("menuitem", { name: "Message" })).toHaveAttribute(
      "href",
      "/messages?with=ada1234"
    );
    expect(screen.queryByRole("menuitem", { name: /view profile/i })).toBeNull();
  });

  it("offers nothing to open where the channel is not", async () => {
    await open();

    expect(screen.queryByRole("menuitem", { name: "Message" })).toBeNull();
  });

  it("only offers to ask when the server says the reader may", async () => {
    await open();
    expect(screen.queryByRole("menuitem", { name: "Ask to message" })).toBeNull();
  });

  it("offers it when it does", async () => {
    mocks.permission.mockReturnValue({ data: { permission: "may_request" } });
    await open();

    await userEvent.click(await screen.findByRole("menuitem", { name: "Ask to message" }));
    expect(mocks.requestMessage).toHaveBeenCalledWith({ data: { user_id: 7 } }, expect.anything());
  });

  it("confirms before removing a connection, and does not guess what it costs", async () => {
    mocks.connections.mockReturnValue({
      data: { accepted: [buildContactGrant({ user_id: 7 })], incoming: [], outgoing: [] },
    });
    await open();
    await userEvent.click(await screen.findByRole("menuitem", { name: "Remove connection" }));

    // Whether the channel survives depends on the other account's own policy,
    // which is not this dialog's to read out. So it says what is certain.
    expect(await screen.findByText(/If nothing else lets the two of you message/i)).toBeVisible();
    expect(mocks.removeConnection).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Remove connection" }));
    await waitFor(() =>
      expect(mocks.removeConnection).toHaveBeenCalledWith({ userId: 7 }, expect.anything())
    );
  });

  it("does not offer connecting to somebody already asked", async () => {
    mocks.connections.mockReturnValue({
      data: { accepted: [], incoming: [], outgoing: [buildContactGrant({ user_id: 7 })] },
    });
    await open();

    expect(screen.queryByRole("menuitem", { name: "Connect" })).toBeNull();
  });
});
