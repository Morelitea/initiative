/**
 * What the router actually resolves each URL to.
 *
 * The initiative subtree puts a tool tab (`/i/5/projects`) beside the
 * initiative's own static children (`/i/5/settings`, `/i/5/apps/3`), and every
 * link in the app is a plain string rather than a typed route id — so nothing
 * else checks that a built path lands where it was meant to. These failures
 * would otherwise appear only at runtime, as a blank page.
 */
import { createRouter } from "@tanstack/react-router";
import { describe, expect, it } from "vitest";

import { routeTree } from "@/routeTree.gen";

const router = createRouter({ routeTree });

/**
 * The id of the innermost route a pathname resolves to.
 *
 * A path under `/g/{id}` with no page behind it still matches the guild
 * *layout*, so "nothing serves this" reads as resolving to `GUILD` rather than
 * to null — that is what the deleted-route cases below assert.
 */
function resolvedRouteId(pathname: string): string {
  const matches = router.matchRoutes({ pathname, search: {} }, { preload: true });
  return String(matches.at(-1)?.routeId ?? "__none__");
}

const GUILD = "/_serverRequired/_authenticated/g/$guildId";
const INITIATIVE = `${GUILD}/i/$initiativeId`;

describe("initiative route resolution", () => {
  it.each([
    ["/g/1/i", `${GUILD}/i/`],
    ["/g/1/i/5", `${INITIATIVE}/`],
    ["/g/1/i/5/projects", `${INITIATIVE}/projects/`],
    ["/g/1/i/5/projects/7", `${INITIATIVE}/projects/$projectId/`],
    ["/g/1/i/5/projects/7/settings", `${INITIATIVE}/projects/$projectId/settings`],
    ["/g/1/i/5/projects/7/tasks/22", `${INITIATIVE}/projects/$projectId/tasks/$taskId`],
    ["/g/1/i/5/documents/3", `${INITIATIVE}/documents/$documentId/`],
    ["/g/1/i/5/queues/4", `${INITIATIVE}/queues/$queueId/`],
    ["/g/1/i/5/counter-groups/6", `${INITIATIVE}/counter-groups/$counterGroupId/`],
    [
      "/g/1/i/5/counter-groups/6/counter/9",
      `${INITIATIVE}/counter-groups/$counterGroupId/counter/$counterId`,
    ],
    ["/g/1/i/5/calendars/2", `${INITIATIVE}/calendars/$calendarId/`],
    ["/g/1/i/5/calendars/2/events/8", `${INITIATIVE}/calendars/$calendarId/events/$eventId/`],
    ["/g/1/i/5/dashboards/5", `${INITIATIVE}/dashboards/$dashboardId/`],
  ])("resolves %s", (pathname, routeId) => {
    expect(resolvedRouteId(pathname)).toBe(routeId);
  });

  // The tab routes are siblings of these; a tool segment that collided with
  // one, or a ranking that preferred the dynamic sibling, would swallow them.
  it("keeps the initiative's own children ahead of the tool tabs", () => {
    expect(resolvedRouteId("/g/1/i/5/settings")).toBe(`${INITIATIVE}/settings`);
    expect(resolvedRouteId("/g/1/i/5/apps/3")).toBe(`${INITIATIVE}/apps/$appId`);
  });

  // `gallery` is a static sibling of `$dashboardId` at the same depth.
  it("prefers a static leaf over the id beside it", () => {
    expect(resolvedRouteId("/g/1/i/5/dashboards/gallery")).toBe(`${INITIATIVE}/dashboards/gallery`);
  });

  // Only calendars can be guild-level; those keep their pre-initiative routes.
  it("resolves a guild-level calendar and its events", () => {
    expect(resolvedRouteId("/g/1/calendars/2")).toBe(`${GUILD}/calendars/$calendarId/`);
    expect(resolvedRouteId("/g/1/calendars/2/events/8")).toBe(
      `${GUILD}/calendars/$calendarId/events/$eventId/`
    );
  });

  // The calendar app's own surface — the guild's calendars, not a roll-up of
  // its initiatives'. That is why this one address survives the list below.
  it("resolves the guild's calendars", () => {
    expect(resolvedRouteId("/g/1/calendars")).toBe(`${GUILD}/calendars/`);
  });

  it("resolves the entity-reference resolver", () => {
    expect(resolvedRouteId("/g/1/go/document/42")).toBe(`${GUILD}/go/$refType/$refId`);
  });

  // Deleted on purpose — the guild home is the cross-initiative browse now.
  it.each([
    "/g/1/projects",
    "/g/1/documents",
    "/g/1/queues",
    "/g/1/dashboards",
    "/g/1/counter-groups",
    // Sub-entities moved under their parent tool in the same change.
    "/g/1/tasks/4",
    "/g/1/calendar-events/8",
    // The initiatives tree answers at /i now.
    "/g/1/initiatives",
    "/g/1/initiatives/5",
  ])("no longer serves %s", (path) => {
    expect(resolvedRouteId(path)).toBe(GUILD);
  });
});
