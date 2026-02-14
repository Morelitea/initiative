import { http, HttpResponse } from "msw";
import { buildTask, buildTaskListResponse, buildDefaultTaskStatuses } from "@/__tests__/factories";

export const taskHandlers = [
  http.get("/api/v1/tasks/", () => {
    return HttpResponse.json(buildTaskListResponse());
  }),

  http.patch("/api/v1/tasks/:id", () => {
    return HttpResponse.json(buildTask());
  }),

  http.get("/api/v1/projects/:id/task-statuses/", () => {
    return HttpResponse.json(buildDefaultTaskStatuses());
  }),
];
