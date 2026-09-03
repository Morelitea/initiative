/**
 * Which tabs a person is offered.
 *
 * The AI tab is the one that isn't always there: an installation that gives
 * nobody a connection, and doesn't let people bring their own key, has nothing
 * to put on that page — so it isn't offered rather than opening on a line
 * saying there is nothing here.
 */
import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";

import { UserSettingsLayout } from "./UserSettingsLayout";

const mocks = vi.hoisted(() => ({ ai: vi.fn() }));

vi.mock("@/hooks/useAISettings", () => ({ useMyAI: () => mocks.ai() }));

const connection = (overrides: Record<string, unknown> = {}) => ({
  guild_id: 1,
  guild_name: "Tabletop",
  scope: "guild",
  connection_id: 1,
  label: "House key",
  provider: "anthropic",
  model: null,
  allow_member_keys: false,
  has_member_key: false,
  requires_member_key: false,
  is_selected: true,
  ...overrides,
});

const answerWith = (data: unknown[]) => mocks.ai.mockReturnValue({ data, isError: false });

beforeEach(() => vi.clearAllMocks());

const render = () => renderPage(UserSettingsLayout, { initialRoute: "/profile" });

describe("the settings tabs", () => {
  it("always offers the profile and the account", async () => {
    answerWith([]);
    render();

    expect(await screen.findByRole("tab", { name: "Profile" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Account" })).toBeInTheDocument();
  });

  it("leaves out AI when there is no connection to configure", async () => {
    answerWith([]);
    render();

    await screen.findByRole("tab", { name: "Profile" });
    expect(screen.queryByRole("tab", { name: "AI" })).not.toBeInTheDocument();
  });

  it("leaves out AI when every connection needs a key nobody may supply", async () => {
    answerWith([connection({ requires_member_key: true, allow_member_keys: false })]);
    render();

    await screen.findByRole("tab", { name: "Profile" });
    expect(screen.queryByRole("tab", { name: "AI" })).not.toBeInTheDocument();
  });

  it("offers AI for a connection that works as it stands", async () => {
    answerWith([connection()]);
    render();

    expect(await screen.findByRole("tab", { name: "AI" })).toBeInTheDocument();
  });

  it("offers AI when a key of your own is allowed", async () => {
    answerWith([connection({ requires_member_key: true, allow_member_keys: true })]);
    render();

    expect(await screen.findByRole("tab", { name: "AI" })).toBeInTheDocument();
  });

  it("offers the Privacy tab, and its path resolves to a real route", async () => {
    answerWith([connection()]);
    const { createRouter } = await import("@tanstack/react-router");
    const { routeTree } = await import("@/routeTree.gen");

    renderPage(UserSettingsLayout);
    expect(await screen.findByRole("tab", { name: /privacy/i })).toBeInTheDocument();

    // Resolved through a real router over the generated tree: a tab pointing
    // at a path nothing registered would render exactly the same.
    const router = createRouter({ routeTree });
    const matches = router.matchRoutes(
      { pathname: "/profile/privacy", search: {} },
      { preload: true }
    );
    expect(String(matches.at(-1)?.routeId)).toContain("profile/privacy");
  });
});
