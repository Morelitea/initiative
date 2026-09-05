import { HttpResponse, http } from "msw";

/**
 * The direct-message surfaces, answering empty.
 *
 * Every page that draws a person now reads some of these — the actions menu on
 * a contact row asks what it may offer about them — so the default is a quiet,
 * complete answer rather than an unhandled request warning in every unrelated
 * suite. A test about any of it overrides the one handler it cares about.
 */
const noGrants = { accepted: [], incoming: [], outgoing: [] };

export const dmHandlers = [
  // An ordinary account: old enough, and reachable by the communities it is
  // in. Surfaces explain an empty list by the reader's own settings, so a
  // default of `private` would have every unrelated suite reading the panel
  // that says so instead of the page it was testing.
  http.get("/api/v1/me/dm-settings", () =>
    HttpResponse.json({
      dm_policy: "community",
      communities: [],
      age_confirmed_at: "2020-01-01T00:00:00Z",
      send_receipts: true,
    })
  ),
  http.get("/api/v1/me/connections", () => HttpResponse.json(noGrants)),
  http.get("/api/v1/me/message-requests", () => HttpResponse.json(noGrants)),
  http.get("/api/v1/me/ignored", () => HttpResponse.json({ items: [], total: 0 })),
  http.get("/api/v1/users/:userId/dm-permission", () =>
    HttpResponse.json({ permission: "denied", may_connect: false })
  ),
  // The same two answers for a page of people at once, which is what a list
  // asks rather than one question per row.
  http.post("/api/v1/me/dm-permissions", () => HttpResponse.json({ permissions: {} })),
  // The contact rosters: the walk of the reader's communities, and the starred
  // list that is not a slice of it.
  http.get("/api/v1/me/contacts", () =>
    HttpResponse.json({ sections: [], page: 1, page_size: 20 })
  ),
  http.get("/api/v1/me/contacts/favorites", () => HttpResponse.json({ items: [], total: 0 })),
];
