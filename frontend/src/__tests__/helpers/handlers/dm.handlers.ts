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
  http.get("/api/v1/me/dm-settings", () =>
    HttpResponse.json({
      dm_policy: "private",
      communities: [],
      age_confirmed_at: "2020-01-01T00:00:00Z",
    })
  ),
  http.get("/api/v1/me/connections", () => HttpResponse.json(noGrants)),
  http.get("/api/v1/me/message-requests", () => HttpResponse.json(noGrants)),
  http.get("/api/v1/me/ignored", () => HttpResponse.json({ items: [], total: 0 })),
  http.get("/api/v1/users/:userId/dm-permission", () =>
    HttpResponse.json({ permission: "denied" })
  ),
];
