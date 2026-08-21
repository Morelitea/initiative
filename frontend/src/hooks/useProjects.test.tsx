/**
 * Favouriting and pinning update the cached project lists in place so the row
 * flips immediately. Those lists are keyed by their query params — and since
 * every list is narrowed to an initiative now, an update that named a few exact
 * keys would silently miss the list the reader is actually looking at, leaving
 * the row showing its old state until some later refetch.
 */
import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { buildProject } from "@/__tests__/factories";
import type { ProjectListResponse } from "@/api/generated/initiativeAPI.schemas";
import { getListProjectsApiV1GGuildIdProjectsGetQueryKey } from "@/api/generated/projects/projects";

const GUILD = 1;

const list = (...items: ReturnType<typeof buildProject>[]): ProjectListResponse => ({
  items,
  total_count: items.length,
  page: 1,
  page_size: 20,
  has_next: false,
});

describe("project list cache keys", () => {
  it("reaches every narrowed list from the endpoint prefix", () => {
    const qc = new QueryClient();
    const project = buildProject({ id: 7, is_favorited: false });

    // The shapes the app actually caches: the sidebar's guild-wide read, an
    // initiative's tab, and that tab's Templates and Archive views.
    const keys = [
      getListProjectsApiV1GGuildIdProjectsGetQueryKey(GUILD),
      getListProjectsApiV1GGuildIdProjectsGetQueryKey(GUILD, { initiative_id: 5 }),
      getListProjectsApiV1GGuildIdProjectsGetQueryKey(GUILD, { template: true, initiative_id: 5 }),
      getListProjectsApiV1GGuildIdProjectsGetQueryKey(GUILD, { archived: true, initiative_id: 5 }),
    ];
    for (const key of keys) qc.setQueryData(key, list(project));

    qc.setQueriesData<ProjectListResponse>(
      { queryKey: getListProjectsApiV1GGuildIdProjectsGetQueryKey(GUILD) },
      (prev) =>
        prev && {
          ...prev,
          items: prev.items.map((p) => (p.id === 7 ? { ...p, is_favorited: true } : p)),
        }
    );

    for (const key of keys) {
      expect(
        qc.getQueryData<ProjectListResponse>(key)?.items[0].is_favorited,
        `stale list for key ${JSON.stringify(key)}`
      ).toBe(true);
    }
  });

  it("does not reach another guild's lists", () => {
    const qc = new QueryClient();
    const otherKey = getListProjectsApiV1GGuildIdProjectsGetQueryKey(2, { initiative_id: 5 });
    qc.setQueryData(otherKey, list(buildProject({ id: 7, is_favorited: false })));

    qc.setQueriesData<ProjectListResponse>(
      { queryKey: getListProjectsApiV1GGuildIdProjectsGetQueryKey(GUILD) },
      (prev) => prev && { ...prev, items: prev.items.map((p) => ({ ...p, is_favorited: true })) }
    );

    expect(qc.getQueryData<ProjectListResponse>(otherKey)?.items[0].is_favorited).toBe(false);
  });
});
