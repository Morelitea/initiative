import { http, HttpResponse } from "msw";
import { buildProject } from "@/__tests__/factories";

export const projectHandlers = [
  http.get("/api/v1/projects/", () => {
    return HttpResponse.json([buildProject()]);
  }),

  http.post("/api/v1/projects/", () => {
    return HttpResponse.json(buildProject());
  }),

  http.post("/api/v1/projects/reorder", () => {
    return HttpResponse.json({ ok: true });
  }),
];
