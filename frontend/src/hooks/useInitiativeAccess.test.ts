import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CommunityEntry } from "@/hooks/useCommunities";
import {
  communityMayAuthorTools,
  communityMayWriteContent,
  useGlobalCreateAccess,
} from "@/hooks/useInitiativeAccess";

const mockUseCommunities = vi.fn();

vi.mock("@/hooks/useCommunities", () => ({ useCommunities: () => mockUseCommunities() }));

// Minimal switcher entries for the cheap, entry-point create gates.
const memberCommunity = (over: Partial<CommunityEntry> = {}) =>
  ({ id: 1, role: "member", ...over }) as CommunityEntry;
const grantEntry = (level: "read" | "read_write") =>
  ({ id: 1, role: "member", accessType: "grant", grantAccessLevel: level }) as CommunityEntry;

describe("community create gates (cheap, switcher-only)", () => {
  it("keeps a member for both authoring and writing", () => {
    expect(communityMayAuthorTools(memberCommunity())).toBe(true);
    expect(communityMayWriteContent(memberCommunity())).toBe(true);
  });

  it("drops a frozen community for both gates", () => {
    const frozen = memberCommunity({ content_read_only: true });
    expect(communityMayAuthorTools(frozen)).toBe(false);
    expect(communityMayWriteContent(frozen)).toBe(false);
  });

  it("lets a read_write grant write but not author, whoever holds it", () => {
    const granted = grantEntry("read_write");
    expect(communityMayAuthorTools(granted)).toBe(false);
    expect(communityMayWriteContent(granted)).toBe(true);
  });

  it("denies a read grant both gates", () => {
    const read = grantEntry("read");
    expect(communityMayAuthorTools(read)).toBe(false);
    expect(communityMayWriteContent(read)).toBe(false);
  });
});

describe("useGlobalCreateAccess", () => {
  it("is false for both when every community is frozen or read-only-granted", () => {
    mockUseCommunities.mockReturnValue({
      communities: [memberCommunity({ id: 1, content_read_only: true }), grantEntry("read")],
    });

    const { result } = renderHook(() => useGlobalCreateAccess());
    expect(result.current).toEqual({ tool: false, task: false });
  });

  it("separates authoring from writing for a read_write grant", () => {
    mockUseCommunities.mockReturnValue({ communities: [grantEntry("read_write")] });

    const { result } = renderHook(() => useGlobalCreateAccess());
    expect(result.current).toEqual({ tool: false, task: true });
  });

  it("is true for both when a member community is present", () => {
    mockUseCommunities.mockReturnValue({ communities: [memberCommunity()] });

    const { result } = renderHook(() => useGlobalCreateAccess());
    expect(result.current).toEqual({ tool: true, task: true });
  });
});
