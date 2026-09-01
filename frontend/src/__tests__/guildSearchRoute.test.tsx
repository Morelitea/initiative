/**
 * The way into guild search, through the router and the palette the app ships.
 *
 * Two things have to be true for search to be reachable at all: the generated
 * route tree has to serve `/g/{id}/search` and load the page from its own
 * chunk, and the command palette has to offer the index's answers plus the way
 * through to the full page. A test that mounts the page component directly
 * proves neither.
 */
import { createRouter } from "@tanstack/react-router";
import { act, fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SearchHit, SearchResults } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { CommandCenter } from "@/components/CommandCenter";
import { routeTree } from "@/routeTree.gen";

import { renderPage } from "./helpers/render";

const SEARCH_ROUTE_ID = "/_serverRequired/_authenticated/g/$guildId/search";

const mocks = vi.hoisted(() => ({ search: vi.fn(), suggest: vi.fn() }));
vi.mock("@/hooks/useSearch", () => ({
  useGuildSearch: (params: unknown) => mocks.search(params),
  useGuildSearchSuggest: () => mocks.suggest(),
}));

const project: SearchHit = {
  entity_type: "project",
  entity_id: 7,
  title: "Riverside kickoff",
  snippet: "the <riverside> stage build",
  initiative_id: 5,
  tool: Tool.project,
  tool_id: 7,
};
const tag: SearchHit = {
  entity_type: "tag",
  entity_id: 12,
  title: "riverside",
  snippet: null,
  initiative_id: null,
  tool: null,
  tool_id: null,
};

const answer = (items: SearchHit[]): SearchResults => ({
  items,
  total: items.length,
  limit: 5,
  offset: 0,
});

const query = (data: SearchResults) => ({ data, isLoading: false, isFetched: true });

/** Answer per scope, the way the endpoint does — the page asks a different
 *  question per tab, and mixing the answers would hide that. */
const withHits = (tools: SearchHit[], tags: SearchHit[]) => {
  mocks.search.mockImplementation((params: { types?: string[] }) =>
    query(answer(params.types?.includes("tag") ? tags : tools))
  );
};

const router = createRouter({ routeTree });

const resolvedRouteId = (pathname: string): string => {
  const matches = router.matchRoutes({ pathname, search: {} }, { preload: true });
  return String(matches.at(-1)?.routeId ?? "__none__");
};

const searchPage = async () => {
  const route = router.routesById[SEARCH_ROUTE_ID];
  const Page = route.options.component as React.ComponentType & {
    preload?: () => Promise<unknown>;
  };
  // The dynamic import the route is declared with: a moved page or a renamed
  // export fails here rather than at a click.
  await Page.preload?.();
  return Page;
};

beforeEach(() => {
  vi.clearAllMocks();
  mocks.suggest.mockReturnValue({ data: [], isLoading: false });
  withHits([], []);
});

describe("the guild search page", () => {
  it("is an address the shipped route tree serves", () => {
    expect(resolvedRouteId("/g/1/search")).toBe(SEARCH_ROUTE_ID);
  });

  it("shows each kind of result under its own heading, linked to where it lives", async () => {
    withHits([project], [tag]);
    const Page = await searchPage();
    renderPage(Page, {
      initialRoute: "/g/$guildId/search",
      routeParams: { guildId: "1" },
      routerSearch: { q: "riverside" },
    });

    const hit = await screen.findByRole("link", { name: /Riverside kickoff/ });
    expect(hit).toHaveAttribute("href", "/g/1/i/5/projects/7");
    // The tag matched too, and lands on its own guild-level page.
    expect(screen.getByRole("link", { name: /^riversideTag$/ })).toHaveAttribute(
      "href",
      "/g/1/tags/12"
    );
    // What matched is marked up inside the snippet rather than shown with the
    // delimiters the database wrapped it in.
    expect(within(hit).getByText("riverside")).toBeInTheDocument();
    expect(hit).not.toHaveTextContent("<riverside>");
  });

  it("offers nothing to open on a tab with nothing behind it", async () => {
    withHits([project], []);
    const Page = await searchPage();
    renderPage(Page, {
      initialRoute: "/g/$guildId/search",
      routeParams: { guildId: "1" },
      routerSearch: { q: "riverside" },
    });

    await screen.findByRole("link", { name: /Riverside kickoff/ });
    expect(screen.getByRole("tab", { name: "Tools" })).toBeEnabled();
    expect(screen.getByRole("tab", { name: "Tags" })).toBeDisabled();
  });

  it("asks nothing until there is something to search for", async () => {
    const Page = await searchPage();
    renderPage(Page, { initialRoute: "/g/$guildId/search", routeParams: { guildId: "1" } });

    expect(await screen.findByText("Search this guild")).toBeInTheDocument();
    expect(mocks.search).toHaveBeenCalledWith(expect.objectContaining({ q: "" }));
    for (const call of mocks.search.mock.calls) {
      expect(call[0].q).toBe("");
    }
  });
});

describe("the command palette", () => {
  it("answers from the index once there is a query, and offers the whole page", async () => {
    mocks.suggest.mockReturnValue({
      data: [
        {
          entity_type: "calendar_event",
          entity_id: 8,
          title: "Riverside read-through",
          initiative_id: 5,
          tool: Tool.calendar,
          tool_id: 2,
        },
      ],
      isLoading: false,
    });

    const { router: pageRouter } = renderPage(CommandCenter, {
      initialRoute: "/g/$guildId",
      routeParams: { guildId: "1" },
    });
    // The router resolves its match a tick after render, remounting what it
    // renders. Opening before that tears the dialog straight back down.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    fireEvent.keyDown(document, { key: "k", metaKey: true });

    const input = await screen.findByRole("combobox");
    await userEvent.type(input, "riverside");

    const hit = await screen.findByText("Riverside read-through", undefined, { timeout: 2000 });
    expect(hit).toBeInTheDocument();

    await userEvent.click(await screen.findByText(/See all results/));
    expect(pageRouter.state.location.pathname).toBe("/g/1/search");
    expect(pageRouter.state.location.searchStr).toContain("q=riverside");
  });
});
