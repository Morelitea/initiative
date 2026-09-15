/**
 * The notice that interrupts a conversation when a device key changes.
 *
 * Its whole job is to be actionable by a person: say whose key changed, show
 * the code they compare it against, and give them the button that lets the
 * conversation carry on. None of those is visible to the type checker -- a
 * notice that renders the wrong name, or no name, compiles exactly the same.
 *
 * Sending is blocked while a change is outstanding, so this component is the
 * only way out of that state. A regression here is not cosmetic.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";

import { PeerKeyChangeNotice } from "./PeerKeyChangeNotice";

const mocks = vi.hoisted(() => ({
  changes: vi.fn(),
  acknowledge: vi.fn(),
}));

vi.mock("@/hooks/useMyMessages", () => ({
  usePeerKeyChanges: () => mocks.changes(),
  useAcknowledgePeerKeyChange: () => ({
    mutate: mocks.acknowledge,
    isPending: false,
  }),
}));

const CHANGE = {
  userId: 7,
  deviceId: "their-replacement",
  now: "a-new-fingerprint",
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

  it("names the person whose key changed", async () => {
    // A browser can be in several conversations. "A device key changed"
    // without saying whose is not something anyone can act on.
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

  it("acknowledges the device that changed, not the person", async () => {
    // Acknowledgement is per device: another device of theirs changing later
    // has to interrupt again.
    mocks.changes.mockReturnValue({ data: [CHANGE] });
    renderPage(() => <PeerKeyChangeNotice nameOf={nameOf} />);

    await userEvent.click(await screen.findByRole("button"));

    expect(mocks.acknowledge).toHaveBeenCalledWith("their-replacement");
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
