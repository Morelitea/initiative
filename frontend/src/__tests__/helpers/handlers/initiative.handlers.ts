import { HttpResponse } from "msw";

import { buildInitiative } from "@/__tests__/factories";

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

  guildHttp.post("/initiatives/:id/join", ({ params }) => {
    return HttpResponse.json(buildInitiative({ id: Number(params.id), join_policy: "open" }));
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
