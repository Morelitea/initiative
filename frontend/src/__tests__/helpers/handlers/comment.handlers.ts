import { HttpResponse } from "msw";

import { communityHttp } from "../communityHttp";

export const commentHandlers = [
  // The community home's activity strip asks for this on every render; tests that
  // care about the feed override it with their own entries.
  communityHttp.get("/comments/recent", () => {
    return HttpResponse.json([]);
  }),
];
