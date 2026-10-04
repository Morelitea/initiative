import { HttpResponse } from "msw";

import { buildDefaultTaskStatuses, buildTask, buildTaskListResponse } from "@/__tests__/factories";

import { communityHttp } from "../communityHttp";

export const taskHandlers = [
  communityHttp.get("/tasks/", () => {
    return HttpResponse.json(buildTaskListResponse());
  }),

  communityHttp.get("/tasks/autocomplete", () => {
    return HttpResponse.json(
      buildTaskListResponse().items.map((task) => ({ id: task.id, title: task.title }))
    );
  }),

  communityHttp.patch("/tasks/:id", () => {
    return HttpResponse.json(buildTask());
  }),

  communityHttp.get("/projects/:id/task-statuses/", () => {
    return HttpResponse.json(buildDefaultTaskStatuses());
  }),
];
