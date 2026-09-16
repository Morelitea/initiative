/**
 * "Ask for help" in the sidebar.
 *
 * The control is always there — the point of it is that somebody who needs
 * help should not have to work out first whether there is anybody to ask. What
 * it does is what the community's setting decides.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { buildGuild } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

vi.mock("@/hooks/useSupport", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/useSupport")>();
  return { ...actual, useAskForHelp: () => ({ mutate: vi.fn(), isPending: false }) };
});

import { FAQ_URL } from "@/hooks/useSupport";

import { AskForHelpButton } from "./AskForHelpButton";

const render = (activeGuild: ReturnType<typeof buildGuild> | null) =>
  renderWithProviders(<AskForHelpButton />, { guilds: { activeGuild } });

describe("AskForHelpButton", () => {
  it("opens the FAQ where the community takes no help requests", () => {
    render(buildGuild({ support_enabled: false }));
    expect(screen.getByRole("link", { name: "Ask for help" })).toHaveAttribute("href", FAQ_URL);
  });

  it("opens the FAQ outside any community", () => {
    // The personal space has no community to ask, and the docs answer most of
    // what would be typed into the form anyway.
    render(null);
    expect(screen.getByRole("link", { name: "Ask for help" })).toHaveAttribute("href", FAQ_URL);
  });

  it("opens the form where the community has switched support on", async () => {
    render(buildGuild({ support_enabled: true }));
    await userEvent.click(screen.getByRole("button", { name: "Ask for help" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });
});
