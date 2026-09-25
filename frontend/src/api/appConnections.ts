/**
 * An installed app's connections: what the guild configured, what each member
 * connected, and what an admin can do about either.
 *
 * Hand-written rather than generated because these routes carry a rule the
 * generated client cannot express on its own: **a stored value only ever
 * travels one way.** A form sends values up; a read comes back with
 * `has_value` and never the value, for the member who typed it and the admin
 * who governs the install alike. Keeping the request and response types beside
 * each other is what makes that visible at the call site.
 *
 * The shapes mirror `backend/app/schemas/tenant/guild_app.py`. Once Orval has
 * run against the new endpoints these can be swapped for the generated
 * equivalents; the field names are already the generated ones.
 */

import { apiClient } from "@/api/client";
import type {
  ConsentAccess,
  GuildAppConsentRead,
  GuildAppMemberConsent,
  GuildAppUpgrade,
  GuildAppUpgradeAsks,
} from "@/api/generated/initiativeAPI.schemas";

/** A localized label, as the manifest supplies it. */
export type LocalizedText = Record<string, string>;

/** One typed input in a connection's form. The closed set the manifest allows. */
export type AppFieldType = "string" | "secret" | "url" | "bool" | "select" | "int";

export interface AppConnectionField {
  key: string;
  type: AppFieldType;
  label: LocalizedText;
  required?: boolean;
  options?: string[];
  /** Returned by the app when a vendor flow finishes — never typed. */
  managed?: boolean;
}

/** What a connection says it will use the credential for. Display only. */
export interface AppAccessHint {
  api?: string;
  scopes?: string[];
}

export interface AppConnection {
  id: string;
  /** `static` is one credential the whole guild uses; `interactive` is each
   *  member's own account at a vendor that authorizes people. */
  scope: "static" | "interactive";
  label: LocalizedText;
  fields: AppConnectionField[];
  access_hint?: AppAccessHint | null;
  /** Non-secret values only — a secret is never sent back. */
  values: Record<string, unknown>;
  /** Which fields hold a value. The whole of what a read discloses. */
  has_value: Record<string, boolean>;
  satisfied: boolean;
  /** Established through the vendor's own flow, which Initiative runs. */
  runs_flow: boolean;
  /** The *viewer's own* state, for an interactive connection: `pending`,
   *  `connected`, `expired` (connect again) or `blocked`. */
  status?: string | null;
  account_label?: string | null;
  blocked: boolean;
}

export interface GuildAppArtifact {
  type: string;
  id: number;
}

/** One initiative an app is placed in, and who may open it there. */
export interface AppPlacement {
  initiative_id: number;
  role_ids: number[];
}

export interface GuildAppDetail {
  id: number;
  guild_id: number;
  listing_uid: string;
  listing_version: string;
  app_kind: string;
  name: string;
  enabled: boolean;
  /** Whether this install tracks its listing. True unless an admin turned it off. */
  auto_update: boolean;
  artifacts: GuildAppArtifact[];
  needs_config: boolean;
  config_state: "unverified" | "ok" | "invalid" | string;
  config_state_detail?: string | null;
  tool?: string | null;
  /** The listing's artwork, for drawing the app outside the marketplace. */
  avatar_url?: string | null;
  features: string[];
  /** The pinned definition, verbatim — what surfaces and connections it has. */
  definition: Record<string, unknown>;
  /** The initiatives its initiative surfaces appear in, each with the roles
   *  allowed to open it there. An initiative not listed is one it is not in. */
  placements: AppPlacement[];
  /** The scopes the seat granted this install. */
  granted_scopes: string[];
  /** The scopes the pinned manifest asks for, in vocabulary order. */
  requested_scopes: string[];
  /** The requested scopes this server lets the seat grant. */
  grantable_scopes: string[];
  admin_only: boolean;
  /** The platform provides this app: no remove, no turning it off. */
  mandatory: boolean;
  /** False when the app's service is not wired up here, or is switched off. */
  available: boolean;
  created_by: number;
  created_at: string;
  updated_at: string;
  connections: AppConnection[];
  /** The viewer's own answers to this app's requests to act as them, one per
   *  purpose, the app-wide one first. Nobody else's. */
  consents?: GuildAppConsentRead[];
  /** The version an update would move this install to. Absent when there is
   *  none — already newest, or nothing published this build can run. */
  update_version?: string | null;
  /** What `update_version` asks for beyond what the install holds, when it asks
   *  for anything: new scopes, new surfaces inside initiatives, and whether the
   *  seat declined it. Absent for a version that asks nothing new. */
  pending_update?: GuildAppUpgradeAsks | null;
}

export interface AppConnectStart {
  connection_id: string;
  /**
   * Where to send the person: the vendor's authorization page, or its install
   * page for a connection an organization installs. Initiative runs the flow
   * and the vendor returns the person to Initiative's callback.
   */
  connect_url: string;
  /** The viewer's state on this connection before the flow runs. */
  status: string;
}

export interface AppMemberConnection {
  connection_id: string;
  user_id: number;
  status: string;
  account_label?: string | null;
  blocked: boolean;
  blocked_by_id?: number | null;
  created_at: string;
  updated_at: string;
}

export interface AppConnectionSummary {
  connection_id: string;
  label: LocalizedText;
  connected_count: number;
  blocked_count: number;
  member_count: number;
}

export interface AppMembersResponse {
  summary: AppConnectionSummary[];
  items: AppMemberConnection[];
  /** Every member's answers to the app's requests to act as them. */
  consents: GuildAppMemberConsent[];
}

/** A value being set, or `null` to clear it. A key left out is untouched. */
export type AppConfigValue = string | number | boolean | null;

const base = (guildId: number, appId: number) => `/c/${guildId}/apps/${appId}`;

export const getGuildApp = (guildId: number, appId: number) =>
  apiClient.get<GuildAppDetail>(base(guildId, appId)).then((r) => r.data);

export const updateGuildAppConfig = (
  guildId: number,
  appId: number,
  values: Record<string, Record<string, AppConfigValue>>
) =>
  apiClient.put<GuildAppDetail>(`${base(guildId, appId)}/config`, { values }).then((r) => r.data);

/** Move to the offered version. `consent` is required when it asks for more:
 *  the version the seat was shown and the scopes it grants with it. */
export const upgradeGuildApp = (guildId: number, appId: number, consent?: GuildAppUpgrade) =>
  apiClient.post<GuildAppDetail>(`${base(guildId, appId)}/upgrade`, consent).then((r) => r.data);

/** Keep the pinned version and stop being asked about `version`. */
export const declineGuildAppUpgrade = (guildId: number, appId: number, version: string) =>
  apiClient
    .post<GuildAppDetail>(`${base(guildId, appId)}/upgrade/decline`, { version })
    .then((r) => r.data);

export const connectGuildApp = (guildId: number, appId: number, connectionId: string) =>
  apiClient
    .post<AppConnectStart>(`${base(guildId, appId)}/connections/${connectionId}/connect`)
    .then((r) => r.data);

export const disconnectGuildApp = (guildId: number, appId: number, connectionId: string) =>
  apiClient
    .delete<void>(`${base(guildId, appId)}/connections/${connectionId}`)
    .then(() => undefined);

export const getGuildAppMembers = (guildId: number, appId: number) =>
  apiClient.get<AppMembersResponse>(`${base(guildId, appId)}/members`).then((r) => r.data);

const memberConnection = (guildId: number, appId: number, userId: number, connectionId: string) =>
  `${base(guildId, appId)}/members/${userId}/connections/${connectionId}`;

export const revokeMemberConnection = (
  guildId: number,
  appId: number,
  userId: number,
  connectionId: string
) =>
  apiClient
    .delete<void>(memberConnection(guildId, appId, userId, connectionId))
    .then(() => undefined);

export const blockMemberConnection = (
  guildId: number,
  appId: number,
  userId: number,
  connectionId: string
) =>
  apiClient
    .post<void>(`${memberConnection(guildId, appId, userId, connectionId)}/block`)
    .then(() => undefined);

export const unblockMemberConnection = (
  guildId: number,
  appId: number,
  userId: number,
  connectionId: string
) =>
  apiClient
    .delete<void>(`${memberConnection(guildId, appId, userId, connectionId)}/block`)
    .then(() => undefined);

export const revokeAllMemberConnections = (guildId: number, appId: number) =>
  apiClient.post<void>(`${base(guildId, appId)}/revoke-all`).then(() => undefined);

// --- acting as a member ------------------------------------------------------
// The seat's two routes end answers and cannot give one: whose name an app may
// carry is answered by that person.

/** End every answer one member gave this app, pending requests included. */
export const revokeMemberConsents = (guildId: number, appId: number, userId: number) =>
  apiClient
    .delete<void>(`${base(guildId, appId)}/members/${userId}/consents`)
    .then(() => undefined);

/** End every member's answers to this app, without uninstalling it. */
export const revokeAllMemberConsents = (guildId: number, appId: number) =>
  apiClient.post<void>(`${base(guildId, appId)}/consents/revoke-all`).then(() => undefined);

// An app asks for one purpose at a time; the member answers each on its own.
// Again no user id: the caller is the member being asked.

/** Allow one of the app's requests, at `access` — never more than it asked. */
export const grantAppConsent = (
  guildId: number,
  appId: number,
  consentId: number,
  access: ConsentAccess
) =>
  apiClient
    .put<GuildAppConsentRead>(`${base(guildId, appId)}/consents/${consentId}`, { access })
    .then((r) => r.data);

/** Decline a request, or withdraw what was allowed. */
export const revokeAppConsent = (guildId: number, appId: number, consentId: number) =>
  apiClient.delete<void>(`${base(guildId, appId)}/consents/${consentId}`).then(() => undefined);
