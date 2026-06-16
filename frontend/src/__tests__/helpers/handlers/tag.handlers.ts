import { HttpResponse } from "msw";

import { guildHttp } from "../guildHttp";

export const tagHandlers = [
  guildHttp.get("/tags/", () => {
    return HttpResponse.json([]);
  }),
];
