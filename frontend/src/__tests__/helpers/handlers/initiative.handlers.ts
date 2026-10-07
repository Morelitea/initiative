import { HttpResponse } from "msw";

import { buildInitiative, buildInitiativeJoinRequest, buildPage } from "@/__tests__/factories";

import { communityHttp } from "../communityHttp";

export const initiativeHandlers = [
  communityHttp.get("/initiatives/", () => {
    return HttpResponse.json([buildInitiative()]);
  }),

  communityHttp.post("/initiatives/", () => {
    return HttpResponse.json(buildInitiative());
  }),

  // Nothing on offer by default: every surface that reads the directory keeps
  // rendering as it did before this feature unless a test says otherwise.
  communityHttp.get("/initiatives/directory", () => {
    return HttpResponse.json([]);
  }),

  // MSW matches handlers in order, so this pattern is declared after the
  // literal `/initiatives/directory` route it would also match.
  communityHttp.get("/initiatives/:id", ({ params }) => {
    const id = Number(params.id);
    if (!Number.isFinite(id)) {
      return undefined;
    }
    return HttpResponse.json(buildInitiative({ id }));
  }),

  // An empty roster, and nobody matching a member search, unless a test says
  // otherwise.
  communityHttp.get("/initiatives/:id/members", () => HttpResponse.json(buildPage([]))),
  communityHttp.get("/initiatives/:id/members/search", () => HttpResponse.json(buildPage([]))),

  communityHttp.post("/initiatives/:id/join", ({ params }) => {
    return HttpResponse.json(buildInitiative({ id: Number(params.id), join_policy: "open" }));
  }),

  // An empty queue by default — the members tab renders for plenty of tests
  // that have nothing to do with join requests.
  communityHttp.get("/initiatives/:id/join-requests", () => {
    return HttpResponse.json([]);
  }),

  communityHttp.post("/initiatives/:id/join-requests", ({ params }) => {
    return HttpResponse.json(buildInitiativeJoinRequest({ initiative_id: Number(params.id) }), {
      status: 201,
    });
  }),

  communityHttp.post("/initiatives/:id/join-requests/:requestId/approve", ({ params }) => {
    return HttpResponse.json(
      buildInitiativeJoinRequest({
        id: Number(params.requestId),
        initiative_id: Number(params.id),
        status: "approved",
      })
    );
  }),

  communityHttp.post("/initiatives/:id/join-requests/:requestId/deny", ({ params }) => {
    return HttpResponse.json(
      buildInitiativeJoinRequest({
        id: Number(params.requestId),
        initiative_id: Number(params.id),
        status: "denied",
      })
    );
  }),
];
