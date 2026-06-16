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

  guildHttp.get("/initiatives/:id/my-permissions", () => {
    return HttpResponse.json({
      role_id: 1,
      role_name: "project_manager",
      role_display_name: "Project Manager",
      is_manager: true,
      permissions: {
        docs_enabled: true,
        projects_enabled: true,
        create_docs: true,
        create_projects: true,
      },
    });
  }),
];
