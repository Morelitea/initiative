import { useParams } from "@tanstack/react-router";

import { useInitiativeAccess } from "@/hooks/useInitiativeAccess";
import { useInitiatives } from "@/hooks/useInitiatives";
import { GuildAppPage } from "@/pages/apps/GuildAppPage";

/** Reads the install id off the route so the page itself takes a plain prop. */
export function GuildAppRoute() {
  const { appId } = useParams({ strict: false }) as { appId?: string };
  const { isGuildAdmin } = useInitiativeAccess();
  const parsed = Number(appId);
  if (!Number.isFinite(parsed)) return null;
  return <GuildAppPage appId={parsed} viewer={{ isGuildAdmin }} />;
}

/**
 * The same install, read inside one initiative.
 *
 * Both ids come off the route, and so does the standing that decides which
 * surfaces are on offer — a manager of *this* initiative, which says nothing
 * about any other. The mint re-derives all of it under the caller's own
 * session; this only keeps the page from offering a door that would not open.
 */
export function InitiativeAppRoute() {
  const { appId, initiativeId } = useParams({ strict: false }) as {
    appId?: string;
    initiativeId?: string;
  };
  const initiatives = useInitiatives();
  const { isGuildAdmin, canManage } = useInitiativeAccess();

  const parsedApp = Number(appId);
  const parsedInitiative = Number(initiativeId);
  if (!Number.isFinite(parsedApp) || !Number.isFinite(parsedInitiative)) return null;

  const initiative = (initiatives.data ?? []).find((one) => one.id === parsedInitiative);
  return (
    <GuildAppPage
      appId={parsedApp}
      initiativeId={parsedInitiative}
      viewer={{
        isGuildAdmin,
        isInitiativeManager: initiative ? canManage(initiative) : false,
      }}
    />
  );
}
