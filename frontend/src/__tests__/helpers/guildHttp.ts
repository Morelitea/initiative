import { http } from "msw";

/**
 * MSW helper for guild-scoped endpoints.
 *
 * Guild-scoped requests hit `/api/v1/g/{guildId}/...` (path-based tenancy).
 * Rather than repeating that prefix in every handler, register handlers with a
 * RESOURCE-RELATIVE path here and the `/api/v1/g/:guildId` base is applied in
 * one place. `:guildId` matches any guild.
 *
 *   guildHttp.get("/tasks/", resolver)  ->  GET /api/v1/g/:guildId/tasks/
 *
 * Non-guild endpoints (/api/v1/me/*, /api/v1/users/me, /api/v1/auth/*, etc.)
 * keep using `http` directly.
 */
const GUILD_BASE = "/api/v1/g/:guildId";

type GetArgs = Parameters<typeof http.get>;

export const guildHttp = {
  get: (path: string, resolver: GetArgs[1], options?: GetArgs[2]) =>
    http.get(`${GUILD_BASE}${path}`, resolver, options),
  post: (path: string, resolver: GetArgs[1], options?: GetArgs[2]) =>
    http.post(`${GUILD_BASE}${path}`, resolver, options),
  put: (path: string, resolver: GetArgs[1], options?: GetArgs[2]) =>
    http.put(`${GUILD_BASE}${path}`, resolver, options),
  patch: (path: string, resolver: GetArgs[1], options?: GetArgs[2]) =>
    http.patch(`${GUILD_BASE}${path}`, resolver, options),
  delete: (path: string, resolver: GetArgs[1], options?: GetArgs[2]) =>
    http.delete(`${GUILD_BASE}${path}`, resolver, options),
};
