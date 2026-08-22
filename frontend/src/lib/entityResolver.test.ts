/**
 * The `/go` resolver is the only path an id-only link has to a real URL, and
 * the legacy normalizer is what keeps already-sent notification links working
 * after tools moved inside their initiatives. Neither is type-checked against
 * a route, so both are pinned here.
 */
import { QueryClient } from "@tanstack/react-query";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { isEntityRefType, normalizeLegacyTarget, resolveEntityPath } from "@/lib/entityResolver";

const GUILD = 1;
let queryClient: QueryClient;

beforeEach(() => {
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
});

describe("resolveEntityPath", () => {
  it("resolves a tool entity to its initiative-scoped address", async () => {
    server.use(
      guildHttp.get("/projects/:id", () => HttpResponse.json({ id: 7, initiative_id: 5 }))
    );
    await expect(resolveEntityPath(queryClient, GUILD, "project", 7)).resolves.toBe(
      "/i/5/projects/7"
    );
  });

  it("nests a task under the project that owns it", async () => {
    server.use(
      guildHttp.get("/tasks/:id", () =>
        HttpResponse.json({ id: 9, project_id: 4, project: { id: 4, initiative_id: 2 } })
      )
    );
    await expect(resolveEntityPath(queryClient, GUILD, "task", 9)).resolves.toBe(
      "/i/2/projects/4/tasks/9"
    );
  });

  it("falls back to reading the project when the task omits its initiative", async () => {
    server.use(
      guildHttp.get("/tasks/:id", () => HttpResponse.json({ id: 9, project_id: 4, project: null })),
      guildHttp.get("/projects/:id", () => HttpResponse.json({ id: 4, initiative_id: 8 }))
    );
    await expect(resolveEntityPath(queryClient, GUILD, "task", 9)).resolves.toBe(
      "/i/8/projects/4/tasks/9"
    );
  });

  it("nests an event under its calendar, guild-level or not", async () => {
    server.use(
      guildHttp.get("/calendar-events/:id", () =>
        HttpResponse.json({ id: 3, calendar_id: 6, initiative_id: null })
      )
    );
    await expect(resolveEntityPath(queryClient, GUILD, "event", 3)).resolves.toBe(
      "/calendars/6/events/3"
    );
  });

  // Deleted, or invisible to this reader — the caller lands on the guild home
  // rather than a URL that 404s.
  it("returns null when the entity can't be read", async () => {
    server.use(guildHttp.get("/documents/:id", () => new HttpResponse(null, { status: 404 })));
    await expect(resolveEntityPath(queryClient, GUILD, "document", 99)).resolves.toBeNull();
  });

  it("returns null for an unknown ref type or a non-numeric id", async () => {
    await expect(resolveEntityPath(queryClient, GUILD, "widget", 1)).resolves.toBeNull();
    await expect(resolveEntityPath(queryClient, GUILD, "project", Number.NaN)).resolves.toBeNull();
  });

  it("recognises exactly the ref types it can resolve", () => {
    expect(isEntityRefType("counter-group")).toBe(true);
    expect(isEntityRefType("counter_group")).toBe(false);
    expect(isEntityRefType("user")).toBe(false);
  });
});

describe("normalizeLegacyTarget", () => {
  it("maps a stored pre-nesting target onto the resolver", () => {
    expect(normalizeLegacyTarget("/tasks/4")).toBe("/go/task/4");
    expect(normalizeLegacyTarget("/projects/12")).toBe("/go/project/12");
    expect(normalizeLegacyTarget("/documents/3")).toBe("/go/document/3");
    expect(normalizeLegacyTarget("/calendar-events/8")).toBe("/go/event/8");
  });

  it("rewrites the initiative paths directly — no lookup needed", () => {
    expect(normalizeLegacyTarget("/initiatives/6")).toBe("/i/6");
    expect(normalizeLegacyTarget("/initiatives")).toBe("/i");
  });

  it("sends a deleted list page to the guild home", () => {
    expect(normalizeLegacyTarget("/projects")).toBe("/");
    expect(normalizeLegacyTarget("/calendar")).toBe("/");
  });

  it("leaves a current path alone", () => {
    expect(normalizeLegacyTarget("/i/5/projects/7")).toBe("/i/5/projects/7");
    expect(normalizeLegacyTarget("/settings/data")).toBe("/settings/data");
    expect(normalizeLegacyTarget("settings/data")).toBe("/settings/data");
  });
});
