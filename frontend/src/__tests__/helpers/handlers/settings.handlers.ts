import { http, HttpResponse } from "msw";

export const settingsHandlers = [
  http.get("/api/v1/settings/roles", () => {
    return HttpResponse.json({
      admin: "Admin",
      project_manager: "Project Manager",
      member: "Member",
    });
  }),
];
