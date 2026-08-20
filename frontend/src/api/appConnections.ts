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
  /** Written by the app itself when it finishes a vendor flow — never typed. */
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
  connect_path?: string | null;
  /** The *viewer's own* state, for an interactive connection. */
  status?: string | null;
  account_label?: string | null;
  blocked: boolean;
}

export interface GuildAppArtifact {
  type: string;
  id: number;
}

export interface GuildAppDetail {
  id: number;
  guild_id: number;
  listing_uid: string;
  listing_version: string;
  app_kind: string;
  name: string;
  enabled: boolean;
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
  /** Which initiatives its initiative surfaces appear in. `{}` is all of them. */
  placement: Record<string, unknown>;
  admin_only: boolean;
  /** The platform provides this app: no remove, no turning it off. */
  mandatory: boolean;
  /** False when the app's service is not wired up here, or is switched off. */
  available: boolean;
  /** Whether this app is one that acts as members, and so has something for
   *  each of them to authorize. */
  delegates: boolean;
  created_by_id: number;
  created_at: string;
  updated_at: string;
  connections: AppConnection[];
  /** The viewer's own authorization, so the page draws it without a second
   *  request. Says nothing about anybody else. */
  delegation?: AppDelegation | null;
}

export interface AppConnectStart {
  connection_id: string;
  connection_ref: string;
  connect_path: string;
  /**
   * Where to send the member: the app's own address, assembled server-side from
   * the deployment's registration plus the manifest's path, carrying the opaque
   * handle the app stores its result against. Absent when this deployment has
   * no live registration for the app — there is nowhere to send anyone.
   */
  connect_url?: string | null;
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

/** One member's authorization for the app to act as them, in an admin's view. */
export interface AppMemberDelegation {
  user_id: number;
  can_read: boolean;
  can_write: boolean;
  revoked: boolean;
  granted_at: string;
  revoked_at?: string | null;
  updated_at: string;
}

export interface AppMembersResponse {
  summary: AppConnectionSummary[];
  items: AppMemberConnection[];
  delegations: AppMemberDelegation[];
}

/**
 * What the viewer has authorized this app to do as them.
 *
 * Answerable whether or not they ever have: `granted` false with a
 * `revoked_at` is somebody who withdrew, and `granted` false without one is
 * somebody who was never asked. The page says different things for each.
 */
export interface AppDelegation {
  granted: boolean;
  can_read: boolean;
  can_write: boolean;
  granted_at?: string | null;
  revoked_at?: string | null;
  confirmed_factor?: string | null;
}

/** A value being set, or `null` to clear it. A key left out is untouched. */
export type AppConfigValue = string | number | boolean | null;

const base = (guildId: number, appId: number) => `/g/${guildId}/apps/${appId}`;

export const getGuildApp = (guildId: number, appId: number) =>
  apiClient.get<GuildAppDetail>(base(guildId, appId)).then((r) => r.data);

export const updateGuildAppConfig = (
  guildId: number,
  appId: number,
  values: Record<string, Record<string, AppConfigValue>>
) =>
  apiClient.put<GuildAppDetail>(`${base(guildId, appId)}/config`, { values }).then((r) => r.data);

export const upgradeGuildApp = (guildId: number, appId: number) =>
  apiClient.post<GuildAppDetail>(`${base(guildId, appId)}/upgrade`).then((r) => r.data);

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
// These take no user id on purpose: whose name an app may carry is answered by
// that person and nobody else, so the caller *is* the subject. The one admin
// route below ends an authorization and cannot create one.

export const grantAppDelegation = (guildId: number, appId: number, canWrite: boolean) =>
  apiClient
    .put<AppDelegation>(`${base(guildId, appId)}/delegation`, { can_write: canWrite })
    .then((r) => r.data);

export const revokeAppDelegation = (guildId: number, appId: number) =>
  apiClient.delete<void>(`${base(guildId, appId)}/delegation`).then(() => undefined);

export const revokeMemberDelegation = (guildId: number, appId: number, userId: number) =>
  apiClient
    .delete<void>(`${base(guildId, appId)}/members/${userId}/delegation`)
    .then(() => undefined);

export const revokeAllMemberDelegations = (guildId: number, appId: number) =>
  apiClient.post<void>(`${base(guildId, appId)}/delegations/revoke-all`).then(() => undefined);
