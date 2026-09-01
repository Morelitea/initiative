import { HttpResponse } from "msw";

import { buildInitiative, buildInitiativeJoinRequest } from "@/__tests__/factories";

import { guildHttp } from "../guildHttp";

export const initiativeHandlers = [
  guildHttp.get("/initiatives/", () => {
    return HttpResponse.json([buildInitiative()]);
  }),

  guildHttp.post("/initiatives/", () => {
    return HttpResponse.json(buildInitiative());
  }),

  // Nothing on offer by default: every surface that reads the directory keeps
  // rendering as it did before this feature unless a test says otherwise.
  guildHttp.get("/initiatives/directory", () => {
    return HttpResponse.json([]);
  }),

  // MSW matches handlers in order, so this pattern is declared after the
  // literal `/initiatives/directory` route it would also match.
  guildHttp.get("/initiatives/:id", ({ params }) => {
    const id = Number(params.id);
    if (!Number.isFinite(id)) {
      return undefined;
    }
    return HttpResponse.json(buildInitiative({ id }));
  }),

  guildHttp.post("/initiatives/:id/join", ({ params }) => {
    return HttpResponse.json(buildInitiative({ id: Number(params.id), join_policy: "open" }));
  }),

  // An empty queue by default — the members tab renders for plenty of tests
  // that have nothing to do with join requests.
  guildHttp.get("/initiatives/:id/join-requests", () => {
    return HttpResponse.json([]);
  }),

  guildHttp.get("/initiatives/:id/join-requests/me", () => {
    return HttpResponse.json([]);
  }),

  guildHttp.post("/initiatives/:id/join-requests", ({ params }) => {
    return HttpResponse.json(buildInitiativeJoinRequest({ initiative_id: Number(params.id) }), {
      status: 201,
    });
  }),

  guildHttp.post("/initiatives/:id/join-requests/:requestId/approve", ({ params }) => {
    return HttpResponse.json(
      buildInitiativeJoinRequest({
        id: Number(params.requestId),
        initiative_id: Number(params.id),
        status: "approved",
      })
    );
  }),

  guildHttp.post("/initiatives/:id/join-requests/:requestId/deny", ({ params }) => {
    return HttpResponse.json(
      buildInitiativeJoinRequest({
        id: Number(params.requestId),
        initiative_id: Number(params.id),
        status: "denied",
      })
    );
  }),

  guildHttp.get("/initiatives/:id/my-permissions", () => {
    return HttpResponse.json({
      role_id: 1,
      role_name: "project_manager",
      role_display_name: "Project Manager",
      is_manager: true,
      permissions: {
        documents_enabled: true,
        projects_enabled: true,
        create_documents: true,
        create_projects: true,
      },
    });
  }),
];
