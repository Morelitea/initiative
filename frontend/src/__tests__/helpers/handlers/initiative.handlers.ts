import { http, HttpResponse } from "msw";
import { buildInitiative } from "@/__tests__/factories";

export const initiativeHandlers = [
  http.get("/api/v1/initiatives/", () => {
    return HttpResponse.json([buildInitiative()]);
  }),

  http.post("/api/v1/initiatives/", () => {
    return HttpResponse.json(buildInitiative());
  }),

  http.get("/api/v1/initiatives/:id/my-permissions", () => {
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
