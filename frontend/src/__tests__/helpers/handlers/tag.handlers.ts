import { HttpResponse } from "msw";

import { communityHttp } from "../communityHttp";

export const tagHandlers = [
  communityHttp.get("/tags/", () => {
    return HttpResponse.json([]);
  }),
];
