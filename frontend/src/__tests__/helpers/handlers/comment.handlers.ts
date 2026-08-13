import { HttpResponse } from "msw";

import { guildHttp } from "../guildHttp";

export const commentHandlers = [
  // The guild home's activity strip asks for this on every render; tests that
  // care about the feed override it with their own entries.
  guildHttp.get("/comments/recent", () => {
    return HttpResponse.json([]);
  }),
];
