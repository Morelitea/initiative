import { describe, expect, it } from "vitest";

import { shouldPinSuspendedGuildToSettings } from "./$guildId";

describe("shouldPinSuspendedGuildToSettings", () => {
  const guildId = 5;

  it("pins content pages of the suspended guild to settings", () => {
    expect(shouldPinSuspendedGuildToSettings("/g/5", guildId)).toBe(true);
    expect(shouldPinSuspendedGuildToSettings("/g/5/", guildId)).toBe(true);
    expect(shouldPinSuspendedGuildToSettings("/g/5/tasks", guildId)).toBe(true);
    expect(shouldPinSuspendedGuildToSettings("/g/5/documents/12", guildId)).toBe(true);
  });

  it("does not redirect the settings surface itself", () => {
    expect(shouldPinSuspendedGuildToSettings("/g/5/settings", guildId)).toBe(false);
    expect(shouldPinSuspendedGuildToSettings("/g/5/settings/danger-zone", guildId)).toBe(false);
  });

  it("lets pending navigations OUT of the guild through (no redirect trap)", () => {
    // The router publishes the pending target location while the suspended
    // guild's layout is still mounted — these must not bounce back to settings.
    expect(shouldPinSuspendedGuildToSettings("/", guildId)).toBe(false);
    expect(shouldPinSuspendedGuildToSettings("/my-projects", guildId)).toBe(false);
    expect(shouldPinSuspendedGuildToSettings("/profile", guildId)).toBe(false);
    expect(shouldPinSuspendedGuildToSettings("/g/6/", guildId)).toBe(false);
    expect(shouldPinSuspendedGuildToSettings("/g/6/settings", guildId)).toBe(false);
  });

  it("does not treat a prefix-overlapping guild id as this guild", () => {
    expect(shouldPinSuspendedGuildToSettings("/g/55/tasks", guildId)).toBe(false);
  });
});
