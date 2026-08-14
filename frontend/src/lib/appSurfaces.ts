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
 * A surface says where it renders and who it is for, and both are read against
 * the reader: the same surface can be a guild-wide entry and an entry inside
 * each initiative, admitting different people in each place. Nothing here
 * decides access — the mint does that, under the caller's own session. This
 * decides what is worth offering, so a reader is not handed a door that would
 * not open.
 */

import type { LocalizedText } from "@/api/appConnections";

export interface AppEmbed {
  id: string;
  path: string;
  /** Where it renders. Absent means guild-wide, the only placement there was. */
  scopes?: string[];
  visibility?: string;
  name?: LocalizedText;
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

/** Who is looking, as far as a surface is concerned. */
export interface SurfaceViewer {
  isGuildAdmin: boolean;
  /** Only meaningful inside an initiative — there is nothing else to manage. */
  isInitiativeManager?: boolean;
}

/** Loose shape so this reads both the list and detail payloads. */
export interface AppSurfaceSource {
  tool?: string | null;
  artifacts?: { type: string; id: number }[];
  definition?: Record<string, unknown> | null;
  /** Where the guild put this app. `{}` — the default — is every initiative. */
  placement?: Record<string, unknown> | null;
}

/**
 * Whether an app's initiative surfaces appear in one initiative.
 *
 * Placement is the guild's own answer to where an app belongs, so unlike a
 * surface's audience it reads the same for everyone — an admin who narrowed it
 * narrowed it for themselves too.
 */
export const placedIn = (
  app: Pick<AppSurfaceSource, "placement">,
  initiativeId: number
): boolean => {
  const chosen = app.placement?.initiatives;
  return Array.isArray(chosen) ? chosen.includes(initiativeId) : true;
};

/**
 * Whether a reader clears the rung a surface named.
 *
 * The ladder, mirroring the manifest vocabulary: `member` ⊂ `initiative_manager`
 * ⊂ `guild_admin`, and a guild admin clears every rung. A reader with no
 * initiative in hand leaves `isInitiativeManager` unset and is measured on the
 * rungs that remain, so the same value can mean an initiative's managers inside
 * it and the guild's admins outside. Anything unrecognized is not offered.
 */
export const clearsVisibility = (required: string | undefined, viewer: SurfaceViewer): boolean => {
  if (viewer.isGuildAdmin) return true;
  if (!required || required === "member") return true;
  if (required === "initiative_manager") return viewer.isInitiativeManager === true;
  return false;
};

/**
 * The embedded surfaces an app offers this reader, in one place.
 *
 * A surface may declare either scope or both, so this is a filter rather than a
 * partition — an app's guild-wide page and its per-initiative one are often the
 * same surface reached from two places.
 */
export const appEmbeds = (
  definition: Record<string, unknown> | null | undefined,
  scope: SurfaceScope,
  viewer: SurfaceViewer
): AppEmbed[] => {
  const embeds = definition?.embeds;
  if (!Array.isArray(embeds)) return [];
  // Guild-wide there is no initiative to manage, so a reader is measured on the
  // rungs that remain however they were described. Dropped here rather than
  // trusted from each caller, so the mint and this cannot come to disagree.
  const reader: SurfaceViewer = scope === "guild" ? { isGuildAdmin: viewer.isGuildAdmin } : viewer;
  return embeds.filter((embed): embed is AppEmbed => {
    if (typeof embed !== "object" || embed === null) return false;
    const candidate = embed as AppEmbed;
    if (typeof candidate.id !== "string" || typeof candidate.path !== "string") return false;
    // Definitions pinned before surfaces could say where they belong carry no
    // scopes at all, and every one of them is guild-wide.
    const scopes = Array.isArray(candidate.scopes) ? candidate.scopes : ["guild"];
    return scopes.includes(scope) && clearsVisibility(candidate.visibility, reader);
  });
};

/** Whether the app declares any credential to fill in or connect. */
export const appHasConnections = (definition?: Record<string, unknown> | null): boolean =>
  Array.isArray(definition?.connections) && definition.connections.length > 0;

/**
 * Where an app's guild-wide entry leads.
 *
 * A tool-instance app mounts an existing tool, so it links at the tool's own
 * route — the calendar an app created is just a calendar. A service app with
 * surfaces this reader can open gets a page. Anything else has no route, and
 * the caller decides what to do with the row.
 */
export const guildAppPath = (
  app: AppSurfaceSource & { id: number },
  viewer: SurfaceViewer
): string | null => {
  if (app.tool === "calendar") {
    const calendar = (app.artifacts ?? []).find((artifact) => artifact.type === "calendar");
    return calendar ? `/calendars/${calendar.id}` : null;
  }
  return appEmbeds(app.definition, "guild", viewer).length ? `/apps/${app.id}` : null;
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
  initiativeId: number,
  viewer: SurfaceViewer
): string | null => {
  if (app.tool || !placedIn(app, initiativeId)) return null;
  return appEmbeds(app.definition, "initiative", viewer).length
    ? `/initiatives/${initiativeId}/apps/${app.id}`
    : null;
};
