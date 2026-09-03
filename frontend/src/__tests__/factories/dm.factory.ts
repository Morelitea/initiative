import type { ContactGrantRead, IgnoredAccountRead } from "@/api/generated/initiativeAPI.schemas";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

/** One connection or message request, from the reader's side of it. */
export function buildContactGrant(overrides: Partial<ContactGrantRead> = {}): ContactGrantRead {
  counter++;
  return {
    user_id: counter,
    username: `person${counter}`,
    discriminator: 1234,
    avatar_url: null,
    status: "active",
    presence: "offline",
    state: "accepted",
    outgoing: false,
    created_at: "2026-01-15T00:00:00.000Z",
    responded_at: "2026-01-16T00:00:00.000Z",
    ...overrides,
  };
}

/** A row of the reader's own ignore list. */
export function buildIgnoredAccount(
  overrides: Partial<IgnoredAccountRead> = {}
): IgnoredAccountRead {
  counter++;
  return {
    user_id: counter,
    username: `ignored${counter}`,
    discriminator: 4321,
    avatar_url: null,
    created_at: "2026-01-15T00:00:00.000Z",
    ...overrides,
  };
}
