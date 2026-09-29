/**
 * The notice that interrupts a conversation when a device key changes.
 *
 * Its whole job is to be actionable by a person: say whose devices changed,
 * show the safety number they compare, and give them the button that lets the
 * conversation carry on. None of those is visible to the type checker -- a
 * notice that renders the wrong name, or no name, compiles exactly the same.
 *
 * Sending is blocked while a change is outstanding, so this component is the
 * only way out of that state. A regression here is not cosmetic.
 */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";

import { PeerKeyChangeNotice } from "./PeerKeyChangeNotice";

const mocks = vi.hoisted(() => ({
  changes: vi.fn(),
  acknowledge: vi.fn(),
}));

const NUMBER = {
  halves: [
    { userId: 1, digits: "111112222233333444445555566666" },
    { userId: 7, digits: "777778888899999000001234567890" },
  ],
  theirs: "777778888899999000001234567890",
  clears: ["their-replacement"],
  verified: false,
};

vi.mock("@/hooks/useMyMessages", () => ({
  usePeerKeyChanges: () => mocks.changes(),
  usePairSafetyNumber: (userId: number | null) => ({
    data: userId === null ? undefined : NUMBER,
  }),
  useAcknowledgeSafetyNumber: () => ({ mutate: mocks.acknowledge, isPending: false }),
}));

const CHANGE = {
  userId: 7,
  deviceId: "their-replacement",
  now: { fingerprint: "a-new-fingerprint", identityKey: "a-new-identity" },
  at: new Date().toISOString(),
};

const nameOf = (userId: number) => (userId === 7 ? "Rowan" : "somebody else");

beforeEach(() => {
  mocks.changes.mockReset();
  mocks.acknowledge.mockReset();
});

describe("the changed-key notice", () => {
  it("says nothing when no key has changed", () => {
    mocks.changes.mockReturnValue({ data: [] });

    const { container } = renderPage(() => <PeerKeyChangeNotice nameOf={nameOf} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("names the person whose devices changed", async () => {
    // A browser can be in several conversations. "A device changed" without
    // saying whose is not something anyone can act on.
    mocks.changes.mockReturnValue({ data: [CHANGE] });

    renderPage(() => <PeerKeyChangeNotice nameOf={nameOf} />);

    expect(await screen.findByText(/Rowan/)).toBeInTheDocument();
  });

  it("announces itself, because it appears without being navigated to", async () => {
    // It is rendered in response to a send, not a page change, so nothing else
    // would read it out.
    mocks.changes.mockReturnValue({ data: [CHANGE] });

    renderPage(() => <PeerKeyChangeNotice nameOf={nameOf} />);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("shows both halves of the safety number, and releases their devices when it matches", async () => {
    mocks.changes.mockReturnValue({ data: [CHANGE] });
    renderPage(() => <PeerKeyChangeNotice nameOf={nameOf} />);

    await userEvent.click(await screen.findByRole("button", { name: /compare safety number/i }));

    // Five digits at a time, each half under whose it is.
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("11111")).toBeInTheDocument();
    expect(within(dialog).getByText("67890")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: /they match/i }));

    expect(mocks.acknowledge).toHaveBeenCalledWith(
      { userId: 7, number: NUMBER },
      expect.anything()
    );
  });

  it("shows the first change when several are waiting", async () => {
    // One at a time: acknowledging the first brings up the next, so a person
    // is never asked to compare two sets of pictures at once.
    const second = { ...CHANGE, userId: 9, deviceId: "another" };
    mocks.changes.mockReturnValue({ data: [CHANGE, second] });

    renderPage(() => <PeerKeyChangeNotice nameOf={nameOf} />);

    expect(await screen.findByText(/Rowan/)).toBeInTheDocument();
    expect(screen.queryByText(/somebody else/)).not.toBeInTheDocument();
  });
});
