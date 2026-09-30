import { HttpResponse } from "msw";

import { buildProject } from "@/__tests__/factories";

import { guildHttp } from "../guildHttp";

export const projectHandlers = [
  guildHttp.get("/projects/", () => {
    return HttpResponse.json([buildProject()]);
  }),

  guildHttp.post("/projects/", () => {
    return HttpResponse.json(buildProject());
  }),

  guildHttp.post("/projects/reorder", () => {
    return HttpResponse.json({ ok: true });
  }),
];
