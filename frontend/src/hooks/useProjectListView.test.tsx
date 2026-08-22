/**
 * The filter/sort pipeline every projects list now shares. Active projects,
 * templates, and archived projects all read through this hook, so a change
 * here lands on three surfaces at once — and the states differ in exactly two
 * ways that are easy to get wrong: only the active list can be dragged into a
 * manual order, and only it lifts pinned projects out of the list.
 */
import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildProject, buildTagSummary } from "@/__tests__/factories";
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
vi.mock("@/hooks/useDefaultFiltersOpen", () => ({
  useDefaultFiltersOpen: () => [true, vi.fn()],
}));

const PREFIX = "project:list";

const render = (projects: ReturnType<typeof buildProject>[], options = {}) =>
  renderHook(() => useProjectListView({ projects, storagePrefix: PREFIX, ...options })).result
    .current;

const names = (projects: { name: string }[]) => projects.map((p) => p.name);

beforeEach(() => {
  prefs.clear();
});

describe("useProjectListView filtering", () => {
  it("matches the search query against the name, case-insensitively", () => {
    prefs.set(`${PREFIX}:search`, "  RAVEN ");
    const view = render([
      buildProject({ name: "Castle Ravenloft" }),
      buildProject({ name: "Barovia Arc" }),
    ]);
    expect(names(view.filteredProjects)).toEqual(["Castle Ravenloft"]);
  });

  it("narrows to favorites and to the selected tags", () => {
    const tag = buildTagSummary({ id: 42 });
    const favoritedAndTagged = buildProject({
      name: "Both",
      is_favorited: true,
      tags: [tag],
    });
    const projects = [
      favoritedAndTagged,
      buildProject({ name: "Favorite only", is_favorited: true }),
      buildProject({ name: "Tag only", tags: [tag] }),
      buildProject({ name: "Neither" }),
    ];

    expect(names(render(projects, { fixedTagIds: [42] }).filteredProjects)).toEqual([
      "Both",
      "Tag only",
    ]);

    // Favorites is component state rather than a preference, so drive it the
    // way the filter bar does.
    const { result, rerender } = renderHook(() =>
      useProjectListView({ projects, storagePrefix: PREFIX, fixedTagIds: [42] })
    );
    result.current.filterBarProps.onFavoritesOnlyChange(true);
    rerender();
    expect(names(result.current.filteredProjects)).toEqual(["Both"]);
  });

  it("drops projects from initiatives the viewer cannot see", () => {
    const view = render(
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

  it("sorts alphabetically when asked", () => {
    prefs.set(`${PREFIX}:sort`, "alphabetical");
    expect(names(render(projects).sortedProjects)).toEqual(["Alpha", "Bravo", "Charlie"]);
  });

  it("defaults to recently updated on a list that cannot be dragged", () => {
    const view = render(projects);
    expect(view.sortMode).toBe("updated");
    expect(names(view.sortedProjects)).toEqual(["Charlie", "Bravo", "Alpha"]);
  });

  it("refuses a stored manual order where nothing can be dragged", () => {
    prefs.set(`${PREFIX}:sort`, "custom");
    // The active list keeps it…
    expect(render(projects, { allowCustomSort: true }).sortMode).toBe("custom");
    // …templates and archived fall back rather than showing an arbitrary order.
    expect(render(projects).sortMode).toBe("updated");
  });

  it("seeds the manual order from the list it can reorder", () => {
    prefs.set(`${PREFIX}:sort`, "custom");
    const view = render(projects, { allowCustomSort: true });
    expect(view.customOrder).toEqual(projects.map((p) => p.id));
  });
});

describe("useProjectListView pinned projects", () => {
  const pinned = buildProject({ name: "Pinned", pinned_at: "2026-04-01T00:00:00.000Z" });
  const plain = buildProject({ name: "Plain" });

  it("lifts pinned projects into their own section for the active list", () => {
    const view = render([pinned, plain], { separatePinned: true });
    expect(names(view.pinnedProjects)).toEqual(["Pinned"]);
    expect(names(view.sortedProjects)).toEqual(["Plain"]);
  });

  it("leaves them in place everywhere else", () => {
    const view = render([pinned, plain]);
    expect(view.pinnedProjects).toEqual([]);
    expect(names(view.sortedProjects)).toHaveLength(2);
  });
});
