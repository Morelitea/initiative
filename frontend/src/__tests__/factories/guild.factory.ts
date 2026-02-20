import type { GuildInviteStatus } from "@/api/generated/initiativeAPI.schemas";
import type { Guild } from "@/types/api";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

export function buildGuild(overrides: Partial<Guild> = {}): Guild {
  counter++;
  return {
    id: counter,
    name: `Guild ${counter}`,
    description: `Description for guild ${counter}`,
    icon_base64: null,
    role: "member",
    position: counter - 1,
    created_at: "2026-01-15T00:00:00.000Z",
    updated_at: "2026-01-15T00:00:00.000Z",
    ...overrides,
  };
}

export function buildGuildInviteStatus(
  overrides: Partial<GuildInviteStatus> = {}
): GuildInviteStatus {
  counter++;
  return {
    code: `invite-code-${counter}`,
    guild_id: counter,
    guild_name: `Guild ${counter}`,
    is_valid: true,
    reason: null,
    expires_at: null,
    max_uses: null,
    uses: 0,
    ...overrides,
  };
}
