import { HttpResponse } from "msw";

import { buildDefaultTaskStatuses, buildTask, buildTaskListResponse } from "@/__tests__/factories";

import { guildHttp } from "../guildHttp";

export const taskHandlers = [
  guildHttp.get("/tasks/", () => {
    return HttpResponse.json(buildTaskListResponse());
  }),

  guildHttp.patch("/tasks/:id", () => {
    return HttpResponse.json(buildTask());
  }),

  guildHttp.get("/projects/:id/task-statuses/", () => {
    return HttpResponse.json(buildDefaultTaskStatuses());
  }),
];
