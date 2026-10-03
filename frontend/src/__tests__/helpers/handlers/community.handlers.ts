import { HttpResponse, http } from "msw";

import { buildCommunity, buildCommunityInviteStatus } from "@/__tests__/factories";

export const communityHandlers = [
  http.get("/api/v1/communities/", () => {
    return HttpResponse.json([buildCommunity()]);
  }),

  http.post("/api/v1/communities/", () => {
    return HttpResponse.json(buildCommunity());
  }),

  http.get("/api/v1/communities/invite/:code", () => {
    return HttpResponse.json(buildCommunityInviteStatus({ is_valid: true }));
  }),
];
