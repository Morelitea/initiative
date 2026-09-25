import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { GuildEntry } from "@/hooks/useGuilds";
import {
  guildMayAuthorTools,
  guildMayWriteContent,
  useGlobalCreateAccess,
} from "@/hooks/useInitiativeAccess";

const mockUseGuilds = vi.fn();

vi.mock("@/hooks/useGuilds", () => ({ useGuilds: () => mockUseGuilds() }));

// Minimal switcher entries for the cheap, entry-point create gates.
const memberGuild = (over: Partial<GuildEntry> = {}) =>
  ({ id: 1, role: "member", ...over }) as GuildEntry;
const grantEntry = (level: "read" | "read_write") =>
  ({ id: 1, role: "member", accessType: "grant", grantAccessLevel: level }) as GuildEntry;

describe("guild create gates (cheap, switcher-only)", () => {
  it("keeps a member for both authoring and writing", () => {
    expect(guildMayAuthorTools(memberGuild())).toBe(true);
    expect(guildMayWriteContent(memberGuild())).toBe(true);
  });

  it("drops a frozen guild for both gates", () => {
    const frozen = memberGuild({ content_read_only: true });
    expect(guildMayAuthorTools(frozen)).toBe(false);
    expect(guildMayWriteContent(frozen)).toBe(false);
  });

  it("lets a read_write grant write but not author, whoever holds it", () => {
    const granted = grantEntry("read_write");
    expect(guildMayAuthorTools(granted)).toBe(false);
    expect(guildMayWriteContent(granted)).toBe(true);
  });

  it("denies a read grant both gates", () => {
    const read = grantEntry("read");
    expect(guildMayAuthorTools(read)).toBe(false);
    expect(guildMayWriteContent(read)).toBe(false);
  });
});

describe("useGlobalCreateAccess", () => {
  it("is false for both when every guild is frozen or read-only-granted", () => {
    mockUseGuilds.mockReturnValue({
      guilds: [memberGuild({ id: 1, content_read_only: true }), grantEntry("read")],
    });

    const { result } = renderHook(() => useGlobalCreateAccess());
    expect(result.current).toEqual({ document: false, task: false });
  });

  it("separates authoring from writing for a read_write grant", () => {
    mockUseGuilds.mockReturnValue({ guilds: [grantEntry("read_write")] });

    const { result } = renderHook(() => useGlobalCreateAccess());
    expect(result.current).toEqual({ document: false, task: true });
  });

  it("is true for both when a member guild is present", () => {
    mockUseGuilds.mockReturnValue({ guilds: [memberGuild()] });

    const { result } = renderHook(() => useGlobalCreateAccess());
    expect(result.current).toEqual({ document: true, task: true });
  });
});
