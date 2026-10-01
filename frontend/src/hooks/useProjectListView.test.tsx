/**
 * The filter/sort pipeline every projects list now shares. Active projects,
 * templates, and archived projects all read through this hook, so a change
 * here lands on three surfaces at once — and the states differ in exactly two
 * ways that are easy to get wrong: only the active list can be dragged into a
 * manual order, and only it lifts pinned projects out of the list.
 *
 * The search and tags narrow on the server, so they are asserted as the
 * request the hook makes; favourites and the sort are the hook's own.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { HttpResponse } from "msw";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildPage, buildProject } from "@/__tests__/factories";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { createTestQueryClient } from "@/__tests__/helpers/render";
import { useProjectListView } from "@/hooks/useProjectListView";

/** Stands in for the server-backed preference map. */
const prefs = new Map<string, unknown>();

vi.mock("@/hooks/useViewPreference", () => ({
  useViewPreference: (key: string, fallback: unknown) => [
    prefs.has(key) ? prefs.get(key) : fallback,
    (next: unknown) => prefs.set(key, next),
    { isLoaded: true },
  ],
}));
vi.mock("@/hooks/useTags", () => ({ useTags: () => ({ data: [] }) }));
vi.mock("@/hooks/useActiveGuildId", () => ({ useActiveGuildId: () => 1 }));

const PREFIX = "project:list";

type Options = Omit<Parameters<typeof useProjectListView>[0], "params" | "storagePrefix">;

/** Serve the list, and mount the hook over it once it has loaded. */
const mount = async (projects: ReturnType<typeof buildProject>[], options: Options = {}) => {
  const requests: URLSearchParams[] = [];
  server.use(
    guildHttp.get("/projects/", ({ request }) => {
      requests.push(new URL(request.url).searchParams);
      return HttpResponse.json(buildPage(projects));
    })
  );
  const client = createTestQueryClient();
  const hook = renderHook(
    () => useProjectListView({ params: { initiative_id: 1 }, storagePrefix: PREFIX, ...options }),
    {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    }
  );
  await waitFor(() => expect(hook.result.current.isLoading).toBe(false));
  return { ...hook, requests };
};

const render = async (projects: ReturnType<typeof buildProject>[], options: Options = {}) =>
  (await mount(projects, options)).result.current;

const names = (projects: { name: string }[]) => projects.map((p) => p.name);

beforeEach(() => {
  prefs.clear();
});

describe("useProjectListView filtering", () => {
  it("asks the list for the stored search and tags, and says the list is narrowed", async () => {
    prefs.set(`${PREFIX}:search`, "  RAVEN ");
    prefs.set(`${PREFIX}:tag-filters`, [42, 7]);

    const { result, requests } = await mount([buildProject({ name: "Castle Ravenloft" })]);

    const params = requests.at(-1)!;
    expect(params.get("initiative_id")).toBe("1");
    expect(params.get("search")).toBe("RAVEN");
    expect(params.getAll("tag_ids")).toEqual(["42", "7"]);
    // What the server answered is shown as is, not matched again here.
    expect(names(result.current.filteredProjects)).toEqual(["Castle Ravenloft"]);
    expect(result.current.narrowed).toBe(true);
  });

  it("asks for the whole list when nothing is set", async () => {
    const { result, requests } = await mount([]);

    const params = requests.at(-1)!;
    expect(params.has("search")).toBe(false);
    expect(params.has("tag_ids")).toBe(false);
    expect(result.current.narrowed).toBe(false);
  });

  it("narrows to favorites itself, which a manual order cannot span", async () => {
    const { result, rerender } = await mount([
      buildProject({ name: "Favorite", is_favorited: true }),
      buildProject({ name: "Not" }),
    ]);

    // Favorites is component state rather than a preference, so drive it the
    // way the filter bar does.
    result.current.filterBarProps.onFavoritesOnlyChange(true);
    rerender();
    expect(names(result.current.filteredProjects)).toEqual(["Favorite"]);
    expect(result.current.narrowed).toBe(true);
  });

  it("drops projects from initiatives the viewer cannot see", async () => {
    const view = await render(
      [
        buildProject({ name: "Visible", initiative_id: 1 }),
        buildProject({ name: "Hidden", initiative_id: 2 }),
      ],
      { viewableInitiativeIds: new Set([1]) }
    );
    expect(names(view.filteredProjects)).toEqual(["Visible"]);
  });
});

describe("useProjectListView sorting", () => {
  const projects = [
    buildProject({ name: "Charlie", updated_at: "2026-03-01T00:00:00.000Z" }),
    buildProject({ name: "Alpha", updated_at: "2026-01-01T00:00:00.000Z" }),
    buildProject({ name: "Bravo", updated_at: "2026-02-01T00:00:00.000Z" }),
  ];

  it("sorts alphabetically when asked", async () => {
    prefs.set(`${PREFIX}:sort`, "alphabetical");
    expect(names((await render(projects)).sortedProjects)).toEqual(["Alpha", "Bravo", "Charlie"]);
  });

  it("defaults to recently updated on a list that cannot be dragged", async () => {
    const view = await render(projects);
    expect(view.sortMode).toBe("updated");
    expect(names(view.sortedProjects)).toEqual(["Charlie", "Bravo", "Alpha"]);
  });

  it("refuses a stored manual order where nothing can be dragged", async () => {
    prefs.set(`${PREFIX}:sort`, "custom");
    // The active list keeps it…
    expect((await render(projects, { allowCustomSort: true })).sortMode).toBe("custom");
    // …templates and archived fall back rather than showing an arbitrary order.
    expect((await render(projects)).sortMode).toBe("updated");
  });

  it("seeds the manual order from the list it can reorder", async () => {
    prefs.set(`${PREFIX}:sort`, "custom");
    const { result } = await mount(projects, { allowCustomSort: true });
    await waitFor(() => expect(result.current.customOrder).toEqual(projects.map((p) => p.id)));
  });
});

describe("useProjectListView pinned projects", () => {
  const pinned = buildProject({ name: "Pinned", pinned_at: "2026-04-01T00:00:00.000Z" });
  const plain = buildProject({ name: "Plain" });

  it("lifts pinned projects into their own section for the active list", async () => {
    const view = await render([pinned, plain], { separatePinned: true });
    expect(names(view.pinnedProjects)).toEqual(["Pinned"]);
    expect(names(view.sortedProjects)).toEqual(["Plain"]);
  });

  it("leaves them in place everywhere else", async () => {
    const view = await render([pinned, plain]);
    expect(view.pinnedProjects).toEqual([]);
    expect(names(view.sortedProjects)).toHaveLength(2);
  });
});
