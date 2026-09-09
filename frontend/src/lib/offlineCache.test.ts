import type { Query } from "@tanstack/react-query";
import { beforeEach, describe, expect, it } from "vitest";

import {
  addGrantOnlyGuildIds,
  guildIdOfPath,
  isPersistablePath,
  noteRestoredIdentity,
  offlineCacheBuster,
  resetGrantOnlyGuildIds,
  restoredIdentityMismatch,
  setGrantOnlyGuildIds,
  shouldPersistQuery,
} from "./offlineCache";

beforeEach(() => {
  resetGrantOnlyGuildIds();
  noteRestoredIdentity(null);
});

describe("guildIdOfPath", () => {
  it("reads the guild out of a guild-addressed path", () => {
    expect(guildIdOfPath("/api/v1/g/42/tasks/7")).toBe(42);
  });

  it("is null for a platform path", () => {
    expect(guildIdOfPath("/api/v1/users/me")).toBeNull();
  });

  it("does not match a guild-looking segment further along the path", () => {
    expect(guildIdOfPath("/api/v1/me/tasks?g=3")).toBeNull();
  });
});

describe("isPersistablePath", () => {
  it("keeps guild content somebody was reading", () => {
    expect(isPersistablePath("/api/v1/g/3/tasks/2866")).toBe(true);
    expect(isPersistablePath("/api/v1/g/3/documents")).toBe(true);
    expect(isPersistablePath("/api/v1/g/12/projects/1/tasks")).toBe(true);
  });

  it("keeps the cross-guild reads the home screens are built from", () => {
    expect(isPersistablePath("/api/v1/me/tasks")).toBe(true);
    expect(isPersistablePath("/api/v1/users/me")).toBe(true);
    expect(isPersistablePath("/api/v1/guilds")).toBe(true);
  });

  it("denies by default — an unlisted path is never persisted", () => {
    expect(isPersistablePath("/api/v1/g/3/uploads/9")).toBe(false);
    expect(isPersistablePath("/api/v1/g/3/imports")).toBe(false);
    expect(isPersistablePath("/api/v1/something-new")).toBe(false);
    expect(isPersistablePath("/other/path")).toBe(false);
  });

  it("never persists configuration, admin or access-grant surfaces", () => {
    for (const path of [
      "/api/v1/auth/providers",
      "/api/v1/config",
      "/api/v1/settings/branding",
      "/api/v1/admin/users",
      "/api/v1/access-grants/",
      "/api/v1/ai-settings",
      "/api/v1/webhooks",
    ]) {
      expect(isPersistablePath(path)).toBe(false);
    }
  });

  it("never persists message surfaces, whose plaintext has its own erase contract", () => {
    expect(isPersistablePath("/api/v1/me/dm-settings")).toBe(false);
    expect(isPersistablePath("/api/v1/me/connections")).toBe(false);
    expect(isPersistablePath("/api/v1/users/8/dm-permission")).toBe(false);
    expect(isPersistablePath("/api/v1/users/8/dm/devices")).toBe(false);
  });

  it("never persists search or trash", () => {
    expect(isPersistablePath("/api/v1/g/3/search")).toBe(false);
    expect(isPersistablePath("/api/v1/g/3/trash")).toBe(false);
  });

  it("excludes a guild reached only by a time-bound PAM grant", () => {
    expect(isPersistablePath("/api/v1/g/9/tasks")).toBe(true);
    setGrantOnlyGuildIds([9]);
    expect(isPersistablePath("/api/v1/g/9/tasks")).toBe(false);
    // Other guilds are unaffected.
    expect(isPersistablePath("/api/v1/g/10/tasks")).toBe(true);
  });

  it("does not let a prefix match spill into a longer sibling name", () => {
    expect(isPersistablePath("/api/v1/g/3/tasks-export")).toBe(false);
  });

  it("widens the grant exclusion without narrowing it, for an unread grant list", () => {
    setGrantOnlyGuildIds([9]);
    // A refresh that could not read the grant list must not drop 9.
    addGrantOnlyGuildIds([]);
    expect(isPersistablePath("/api/v1/g/9/tasks")).toBe(false);
    addGrantOnlyGuildIds([11]);
    expect(isPersistablePath("/api/v1/g/9/tasks")).toBe(false);
    expect(isPersistablePath("/api/v1/g/11/tasks")).toBe(false);
    // A reading that did come back is allowed to replace it.
    setGrantOnlyGuildIds([]);
    expect(isPersistablePath("/api/v1/g/9/tasks")).toBe(true);
  });
});

const query = (key: readonly unknown[], status: "success" | "error" | "pending"): Query =>
  ({ queryKey: key, state: { status } }) as unknown as Query;

describe("shouldPersistQuery", () => {
  it("keeps a successful read of an allowlisted path", () => {
    expect(shouldPersistQuery(query(["/api/v1/g/3/tasks", { page: 1 }], "success"))).toBe(true);
  });

  it("drops anything that is not a success", () => {
    expect(shouldPersistQuery(query(["/api/v1/g/3/tasks"], "error"))).toBe(false);
    expect(shouldPersistQuery(query(["/api/v1/g/3/tasks"], "pending"))).toBe(false);
  });

  it("drops hand-written keys, which are not request paths", () => {
    expect(shouldPersistQuery(query(["dm", "unread"], "success"))).toBe(false);
    expect(shouldPersistQuery(query(["contacts", "community", 3, ""], "success"))).toBe(false);
    expect(shouldPersistQuery(query([{ scope: "guild-app" }], "success"))).toBe(false);
  });
});

describe("offlineCacheBuster", () => {
  it("differs per server, so pointing at another deployment discards the cache", () => {
    expect(offlineCacheBuster("https://a.example")).not.toBe(
      offlineCacheBuster("https://b.example")
    );
  });
});

describe("restoredIdentityMismatch", () => {
  it("is false when nothing was restored", () => {
    expect(restoredIdentityMismatch(7)).toBe(false);
  });

  it("is false when the confirmed user is the one we restored for", () => {
    noteRestoredIdentity(7);
    expect(restoredIdentityMismatch(7)).toBe(false);
  });

  it("is true when sign-out never ran and somebody else signed in", () => {
    noteRestoredIdentity(7);
    expect(restoredIdentityMismatch(8)).toBe(true);
  });

  it("adopts the confirmed identity, so it only fires once per handover", () => {
    noteRestoredIdentity(7);
    expect(restoredIdentityMismatch(8)).toBe(true);
    expect(restoredIdentityMismatch(8)).toBe(false);
  });
});
