import { GuildStatus } from "@/api/generated/initiativeAPI.schemas";

/**
 * The statuses an operator may set from the Guilds tab, least → most
 * restrictive.
 *
 * Mirrors `OPERATOR_SETTABLE_STATUSES` in `app/models/platform/guild.py`, and
 * exists for the same reason it does there: `deleted` is a real status this
 * enum carries, but it is reached by deleting a community and left by
 * restoring one — never by picking it out of a list. Written out rather than
 * filtered from the enum, so adding a status is a decision about whether it
 * belongs in this control.
 */
export const OPERATOR_SETTABLE_STATUSES: GuildStatus[] = [
  GuildStatus.active,
  GuildStatus.read_only,
  GuildStatus.on_hold,
  GuildStatus.suspended,
];

/** Whether a community at this status is reachable by its members at all. */
export const reachesContent = (status: GuildStatus): boolean =>
  status === GuildStatus.active || status === GuildStatus.read_only;
