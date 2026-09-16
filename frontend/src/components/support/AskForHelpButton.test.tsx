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

const available = vi.hoisted(() => ({ current: undefined as boolean | undefined }));

vi.mock("@/hooks/useActiveGuildId", () => ({ useActiveGuildId: () => 3 }));
vi.mock("@/hooks/useSupport", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/useSupport")>();
  return {
    ...actual,
    useSupportAvailability: () => ({
      data: available.current === undefined ? undefined : { available: available.current },
    }),
    useAskForHelp: () => ({ mutate: vi.fn(), isPending: false }),
  };
});

import { FAQ_URL } from "@/hooks/useSupport";

import { AskForHelpButton } from "./AskForHelpButton";

const render = (answer: boolean | undefined) => {
  available.current = answer;
  return renderWithProviders(<AskForHelpButton />);
};

describe("AskForHelpButton", () => {
  it("opens the FAQ where this deployment takes no help requests", () => {
    render(false);
    expect(screen.getByRole("link", { name: "Ask for help" })).toHaveAttribute("href", FAQ_URL);
  });

  it("opens the FAQ before the answer has arrived", () => {
    // The fallback is the one that works without an answer; a form drawn on a
    // guess would be a dead end for as long as the guess was wrong.
    render(undefined);
    expect(screen.getByRole("link", { name: "Ask for help" })).toHaveAttribute("href", FAQ_URL);
  });

  it("opens the form where help requests are taken", async () => {
    render(true);
    await userEvent.click(screen.getByRole("button", { name: "Ask for help" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });
});
