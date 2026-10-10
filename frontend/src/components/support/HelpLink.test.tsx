/**
 * "Ask for help" beside a notice: the form on the notice's topic, the
 * deployment's address, or nothing.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";

type Offer = { mode: "form" | "email" | "none"; contact: string | null; types?: string[] };

const offered = vi.hoisted(() => ({ current: undefined as Offer | undefined }));
const fileMutate = vi.fn();

vi.mock("@/hooks/useTickets", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/useTickets")>();
  return {
    ...actual,
    useTicketAvailability: () => ({
      data:
        offered.current === undefined
          ? undefined
          : { support: { evidence: null, types: [], ...offered.current } },
    }),
    useFileTicket: () => ({ mutate: fileMutate, isPending: false }),
  };
});

import { HelpLink } from "./HelpLink";

describe("HelpLink", () => {
  beforeEach(() => {
    fileMutate.mockClear();
  });

  it("is not drawn where there is nobody to ask", () => {
    offered.current = { mode: "none", contact: null };
    renderWithProviders(<HelpLink topic="community" communityId={3} />);
    expect(screen.queryByRole("button", { name: "Ask for help" })).not.toBeInTheDocument();
  });

  it("shows the address where help requests are not taken", async () => {
    offered.current = { mode: "email", contact: "help@example.org" };
    renderWithProviders(<HelpLink topic="community" communityId={3} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Ask for help" }));
    expect(await screen.findByText("help@example.org")).toBeInTheDocument();
  });

  it("opens the form on the notice's topic", async () => {
    offered.current = { mode: "form", contact: null, types: ["account", "community", "other"] };
    renderWithProviders(<HelpLink topic="community" communityId={3} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Ask for help" }));
    expect(await screen.findByRole("combobox", { name: "What is it about?" })).toHaveTextContent(
      "This community"
    );
  });
});
