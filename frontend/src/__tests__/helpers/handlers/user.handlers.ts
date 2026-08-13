import { HttpResponse, http } from "msw";

import { buildUser } from "@/__tests__/factories";

export const userHandlers = [
  http.get("/api/v1/users/me", () => {
    return HttpResponse.json(buildUser());
  }),
  // View preference writes are debounced, and flushed again on unmount — which
  // lands during cleanup, after a test's own handlers are gone. Answering the
  // write here keeps that flush from surfacing as an unhandled rejection in
  // whichever test happens to be running at the time.
  http.put("/api/v1/user-view-preferences/:scopeKey", () => {
    return HttpResponse.json({ items: {} });
  }),
];
