import { http, HttpResponse } from "msw";
import { buildGuild, buildGuildInviteStatus } from "@/__tests__/factories";

export const guildHandlers = [
  http.get("/api/v1/guilds/", () => {
    return HttpResponse.json([buildGuild()]);
  }),

  http.post("/api/v1/guilds/", () => {
    return HttpResponse.json(buildGuild());
  }),

  http.get("/api/v1/guilds/invite/:code", () => {
    return HttpResponse.json(buildGuildInviteStatus({ is_valid: true }));
  }),
];
