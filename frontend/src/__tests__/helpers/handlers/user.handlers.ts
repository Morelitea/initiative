import { http, HttpResponse } from "msw";
import { buildUser } from "@/__tests__/factories";

export const userHandlers = [
  http.get("/api/v1/users/me", () => {
    return HttpResponse.json(buildUser());
  }),
];
