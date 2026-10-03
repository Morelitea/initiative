import { HttpResponse } from "msw";

import { buildProject } from "@/__tests__/factories";

import { communityHttp } from "../communityHttp";

export const projectHandlers = [
  communityHttp.get("/projects/", () => {
    return HttpResponse.json([buildProject()]);
  }),

  communityHttp.post("/projects/", () => {
    return HttpResponse.json(buildProject());
  }),

  communityHttp.post("/projects/reorder", () => {
    return HttpResponse.json({ ok: true });
  }),
];
