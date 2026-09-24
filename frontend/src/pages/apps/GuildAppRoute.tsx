import { useParams } from "@tanstack/react-router";

import { GuildAppPage } from "@/pages/apps/GuildAppPage";

/** Reads the install id off the route so the page itself takes a plain prop. */
export function GuildAppRoute() {
  const { appId } = useParams({ strict: false }) as { appId?: string };
  const parsed = Number(appId);
  if (!Number.isFinite(parsed)) return null;
  return <GuildAppPage appId={parsed} />;
}

/**
 * The same install, read inside one initiative.
 *
 * Both ids come off the route. Which surfaces are on offer is the server's
 * answer for this reader in this initiative; the mint re-derives it under the
 * caller's own session.
 */
export function InitiativeAppRoute() {
  const { appId, initiativeId } = useParams({ strict: false }) as {
    appId?: string;
    initiativeId?: string;
  };
  const parsedApp = Number(appId);
  const parsedInitiative = Number(initiativeId);
  if (!Number.isFinite(parsedApp) || !Number.isFinite(parsedInitiative)) return null;

  return <GuildAppPage appId={parsedApp} initiativeId={parsedInitiative} />;
}
