/**
 * "Ask for help" in the sidebar.
 *
 * The control is always there — the point of it is that somebody who needs
 * help should not have to work out first whether there is anybody to ask. What
 * it does is what the server's one answer decides.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";

type Offer = { mode: "form" | "email" | "none"; contact: string | null };

const offered = vi.hoisted(() => ({ current: undefined as Offer | undefined }));

vi.mock("@/hooks/useActiveGuildId", () => ({ useActiveGuildId: () => 3 }));
vi.mock("@/hooks/useTickets", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/useTickets")>();
  return {
    ...actual,
    useTicketAvailability: () => ({
      data: offered.current === undefined ? undefined : { support: offered.current },
    }),
    useFileTicket: () => ({ mutate: vi.fn(), isPending: false }),
  };
});

import { AskForHelpButton } from "./AskForHelpButton";

const render = (answer: Offer | boolean | undefined) => {
  offered.current =
    typeof answer === "boolean" ? { mode: answer ? "form" : "none", contact: null } : answer;
  return renderWithProviders(<AskForHelpButton />);
};

describe("AskForHelpButton", () => {
  it("is not drawn where there is nobody to ask", () => {
    // The documentation has its own button; a dead end never stands in for it.
    render(false);
    expect(screen.queryByRole("button", { name: "Ask for help" })).not.toBeInTheDocument();
  });

  it("is not drawn before the answer has arrived", () => {
    // A form drawn on a guess would be a dead end for as long as the guess was
    // wrong.
    render(undefined);
    expect(screen.queryByRole("button", { name: "Ask for help" })).not.toBeInTheDocument();
  });

  it("shows the deployment's address where it takes no requests but gave one", async () => {
    render({ mode: "email", contact: "help@example.org" });
    await userEvent.click(screen.getByRole("button", { name: "Ask for help" }));
    expect(await screen.findByText("help@example.org")).toBeInTheDocument();
  });

  it("opens the form where help requests are taken", async () => {
    render(true);
    await userEvent.click(screen.getByRole("button", { name: "Ask for help" }));
    expect(await screen.findByLabelText("What is this about?")).toBeInTheDocument();
  });
});
