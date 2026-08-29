import type { GuildInviteStatus, GuildRead } from "@/api/generated/initiativeAPI.schemas";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

export function buildGuild(overrides: Partial<GuildRead> = {}): GuildRead {
  counter++;
  return {
    id: counter,
    name: `Guild ${counter}`,
    description: `Description for guild ${counter}`,
    icon_url: null,
    banner_url: null,
    banner_color: "#2563eb",
    banner_text_color: "#ffffff",
    banner_text_align: "center",
    banner_fade: "none",
    online_count: 0,
    role: "member",
    position: counter - 1,
    created_at: "2026-01-15T00:00:00.000Z",
    updated_at: "2026-01-15T00:00:00.000Z",
    member_count: 1,
    tier_name: null,
    content_read_only: false,
    is_community: false,
    categories: [],
    has_adult_content: null,
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
