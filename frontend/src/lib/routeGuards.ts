import { redirect } from "@tanstack/react-router";

import type { RouterContext } from "@/router";

/**
 * beforeLoad for legacy non-guild paths: forward to the active guild's copy
 * of the route (search params included when the route has them), or home when
 * no guild is active.
 */
export function redirectToActiveGuild(to: string) {
  return ({
    context,
    search,
  }: {
    context: RouterContext;
    search?: Record<string, unknown>;
  }): void => {
    const guildId = context.guilds?.activeGuildId;
    if (guildId) {
      throw redirect({
        to,
        params: { guildId: String(guildId) },
        // A runtime `to` makes the router type `search` as the union of every
        // route's schema; the forwarded object is already a valid subset.
        search: (search ?? {}) as never,
      });
    }
    throw redirect({ to: "/" });
  };
}
