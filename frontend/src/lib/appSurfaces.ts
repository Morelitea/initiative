/**
 * What an installed app offers a member, read off its pinned definition.
 *
 * Three shapes, and the sidebar treats each differently:
 *
 * - **A surface** — one or more embedded pages. Opens a page of its own.
 * - **Something to connect** — no page, but a credential the member or an
 *   admin supplies. Opens a dialog where they do that.
 * - **Neither** — it contributes widgets or data to somewhere else. There is
 *   nothing to open, so it does not take a row of its own.
 *
 * A surface says where it renders; *who* may open it there is the server's
 * answer (`surface_access`), computed by the same decision the handoff mint
 * makes: the placement's roles inside an initiative, the community's admins at
 * the community level and on an `admin_only` surface. Nothing here decides
 * access — this decides what is worth offering, so a reader is not handed a
 * door that would not open.
 */

import { initiativeRoute } from "@/lib/tools";

export interface AppEmbed {
  id: string;
  path: string;
  /** Where it renders. Absent means guild-wide, the only placement there was. */
  scopes?: string[];
  /** Opened by the community's admins alone, whatever a placement allows. */
  admin_only?: boolean;
  /** Localized label, keyed by language. */
  name?: Record<string, string>;
  /** Browser features the surface asked its frame for, from the closed
   *  vocabulary the manifest validator checks. Absent means it asked for none. */
  capabilities?: string[];
}

/**
 * The `allow` attribute for a surface's frame.
 *
 * A frame is granted what its manifest named and nothing else, so a surface
 * that named nothing gets an empty attribute. Each entry defaults to the
 * frame's own origin, which is the app's.
 */
export const embedAllow = (embed: Pick<AppEmbed, "capabilities"> | null | undefined): string =>
  (embed?.capabilities ?? []).join("; ");

/** The places a surface can be reached from. */
export type SurfaceScope = "guild" | "initiative";

/** Where the viewer may open one surface, as the server computed it. */
export interface SurfaceAccess {
  surface_id: string;
  openable_guild_wide: boolean;
  openable_initiatives: number[];
}

/** Loose shape so this reads both the list and detail payloads. */
export interface AppSurfaceSource {
  tool?: string | null;
  artifacts?: { type: string; id: number }[];
  definition?: Record<string, unknown> | null;
  /** The initiatives the seat placed this app in, one entry each. */
  placements?: { initiative_id: number }[] | null;
  /** Where the viewer may open each surface. */
  surface_access?: SurfaceAccess[] | null;
}

/**
 * Whether an app's initiative surfaces appear in one initiative.
 *
 * An app appears only where it was placed. Placement is the community's own
 * answer to where an app belongs, so it reads the same for everyone — an admin
 * who left an initiative out left it out for themselves too.
 */
export const placedIn = (
  app: Pick<AppSurfaceSource, "placements">,
  initiativeId: number
): boolean => (app.placements ?? []).some((one) => one.initiative_id === initiativeId);

/** The embedded surfaces a definition declares for one scope, whoever reads. */
export const declaredEmbeds = (
  definition: Record<string, unknown> | null | undefined,
  scope: SurfaceScope
): AppEmbed[] => {
  const embeds = definition?.embeds;
  if (!Array.isArray(embeds)) return [];
  return embeds.filter((embed): embed is AppEmbed => {
    if (typeof embed !== "object" || embed === null) return false;
    const candidate = embed as AppEmbed;
    if (typeof candidate.id !== "string" || typeof candidate.path !== "string") return false;
    // Definitions pinned before surfaces could say where they belong carry no
    // scopes at all, and every one of them is guild-wide.
    const scopes = Array.isArray(candidate.scopes) ? candidate.scopes : ["guild"];
    return scopes.includes(scope);
  });
};

/**
 * The embedded surfaces an app offers this reader in one place.
 *
 * `initiativeId` is where: absent is the community level. A surface may declare
 * either scope or both, so this is a filter rather than a partition — an app's
 * guild-wide page and its per-initiative one are often the same surface reached
 * from two places. What the server did not say may be opened is not offered.
 */
export const appEmbeds = (
  app: Pick<AppSurfaceSource, "definition" | "surface_access"> | null | undefined,
  initiativeId?: number
): AppEmbed[] => {
  const scope: SurfaceScope = initiativeId === undefined ? "guild" : "initiative";
  const access = new Map((app?.surface_access ?? []).map((one) => [one.surface_id, one]));
  return declaredEmbeds(app?.definition, scope).filter((embed) => {
    const answer = access.get(embed.id);
    if (!answer) return false;
    return initiativeId === undefined
      ? answer.openable_guild_wide
      : answer.openable_initiatives.includes(initiativeId);
  });
};

/** Whether the app declares any credential to fill in or connect. */
export const appHasConnections = (definition?: Record<string, unknown> | null): boolean =>
  Array.isArray(definition?.connections) && definition.connections.length > 0;

/**
 * Where an app's guild-wide entry leads.
 *
 * A tool-instance app mounts an existing tool, so it links at the tool's own
 * route — the calendars an app holds are just calendars. It links at the list
 * rather than at one of them, because a member may add more: the app's home is
 * everything it holds, which is still the right address when it holds one. A
 * service app with surfaces this reader can open gets a page. Anything else has
 * no route, and the caller decides what to do with the row.
 */
export const guildAppPath = (app: AppSurfaceSource & { id: number }): string | null => {
  if (app.tool === "calendar") {
    // No `/i/` prefix on purpose: an app is installed per guild, and the
    // calendars it holds belong to no initiative — the guild route is their
    // real address, not a leftover.
    return "/calendars";
  }
  return appEmbeds(app).length ? `/apps/${app.id}` : null;
};

/**
 * Where an app's entry inside one initiative leads.
 *
 * The same install — there is one of it per guild, not one per initiative —
 * opened somewhere narrower. A tool-instance app has none: the tool it mounted
 * already lives in an initiative of its own.
 */
export const initiativeAppPath = (
  app: AppSurfaceSource & { id: number },
  initiativeId: number
): string | null => {
  if (app.tool || !placedIn(app, initiativeId)) return null;
  return appEmbeds(app, initiativeId).length
    ? `${initiativeRoute(initiativeId)}/apps/${app.id}`
    : null;
};
