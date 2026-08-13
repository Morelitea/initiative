import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { buildInitiative, buildInitiativeMember, buildUser } from "@/__tests__/factories";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import type { GuildEntry } from "@/hooks/useGuilds";
import {
  guildMayAuthorTools,
  guildMayWriteContent,
  useGlobalCreateAccess,
  useInitiativeAccess,
} from "@/hooks/useInitiativeAccess";

const mockUseAuth = vi.fn();
const mockUseGuilds = vi.fn();

vi.mock("@/hooks/useAuth", () => ({ useAuth: () => mockUseAuth() }));
vi.mock("@/hooks/useGuilds", () => ({ useGuilds: () => mockUseGuilds() }));

// A guild reached via a PAM grant rather than membership. Grant entries always
// carry role "member" — the break-glass distinction must come from the grant
// level + the holder's server-computed capabilities, never the role field.
const grantGuild = (level: "read" | "read_write") => ({
  id: 1,
  role: "member",
  accessType: "grant",
  grantAccessLevel: level,
});

describe("useInitiativeAccess grant classification", () => {
  it("gives a scoped read grant full view but no create", () => {
    mockUseAuth.mockReturnValue({ user: buildUser({ role: "moderator" }) });
    mockUseGuilds.mockReturnValue({ activeGuild: grantGuild("read") });

    const { result } = renderHook(() => useInitiativeAccess());
    const access = result.current.permissionsFor(buildInitiative());

    expect(access[Tool.project]).toEqual({ view: true, create: false });
    expect(access[Tool.document]).toEqual({ view: true, create: false });
  });

  it("gives a scoped read_write grant (no data.bypass) no create affordances", () => {
    // The request→approve flow: a read_write grant edits existing content
    // only — authoring new tools is denied server-side, so the UI must not
    // offer it.
    mockUseAuth.mockReturnValue({ user: buildUser({ role: "moderator" }) });
    mockUseGuilds.mockReturnValue({ activeGuild: grantGuild("read_write") });

    const { result } = renderHook(() => useInitiativeAccess());
    const access = result.current.permissionsFor(buildInitiative());

    expect(access[Tool.project]).toEqual({ view: true, create: false });
    expect(access[Tool.document]).toEqual({ view: true, create: false });
  });

  it("gives a break-glass read_write grant (data.bypass holder) full create", () => {
    // An operator's read_write grant is break-glass: the backend routes it as
    // a synthetic guild admin, so create affordances stay on.
    mockUseAuth.mockReturnValue({ user: buildUser({ role: "operator" }) });
    mockUseGuilds.mockReturnValue({ activeGuild: grantGuild("read_write") });

    const { result } = renderHook(() => useInitiativeAccess());
    const access = result.current.permissionsFor(buildInitiative());

    expect(access[Tool.project]).toEqual({ view: true, create: true });
    expect(access[Tool.document]).toEqual({ view: true, create: true });
  });

  it("never lets a read grant create even for a data.bypass holder", () => {
    // Break-glass requires read_write; an operator's read grant stays
    // view-only.
    mockUseAuth.mockReturnValue({ user: buildUser({ role: "operator" }) });
    mockUseGuilds.mockReturnValue({ activeGuild: grantGuild("read") });

    const { result } = renderHook(() => useInitiativeAccess());
    const access = result.current.permissionsFor(buildInitiative());

    expect(access[Tool.project]).toEqual({ view: true, create: false });
  });
});

// Minimal switcher entries for the cheap, entry-point create gates.
const memberGuild = (over: Partial<GuildEntry> = {}) =>
  ({ id: 1, role: "member", ...over }) as GuildEntry;
const adminGuild = (over: Partial<GuildEntry> = {}) =>
  ({ id: 1, role: "admin", ...over }) as GuildEntry;
const grantEntry = (level: "read" | "read_write") =>
  ({ id: 1, role: "member", accessType: "grant", grantAccessLevel: level }) as GuildEntry;

describe("guild create gates (cheap, switcher-only)", () => {
  const member = buildUser({ role: "member" });
  const operator = buildUser({ role: "operator" }); // holds data.bypass

  it("keeps a plain member for both authoring and writing", () => {
    expect(guildMayAuthorTools(memberGuild(), member)).toBe(true);
    expect(guildMayWriteContent(memberGuild(), member)).toBe(true);
  });

  it("drops a frozen guild for both gates", () => {
    const frozen = memberGuild({ content_read_only: true });
    expect(guildMayAuthorTools(frozen, member)).toBe(false);
    expect(guildMayWriteContent(frozen, member)).toBe(false);
  });

  it("keeps an admin for both gates", () => {
    expect(guildMayAuthorTools(adminGuild(), member)).toBe(true);
    expect(guildMayWriteContent(adminGuild(), member)).toBe(true);
  });

  it("lets a scoped read_write grant write but not author", () => {
    // The #881 rule: a scoped grant edits existing content (tasks in existing
    // projects) but never authors a new tool. data.bypass makes it break-glass.
    const scoped = grantEntry("read_write");
    expect(guildMayAuthorTools(scoped, member)).toBe(false);
    expect(guildMayWriteContent(scoped, member)).toBe(true);
    expect(guildMayAuthorTools(scoped, operator)).toBe(true); // break-glass authors
  });

  it("denies a read grant both gates", () => {
    const read = grantEntry("read");
    expect(guildMayAuthorTools(read, operator)).toBe(false);
    expect(guildMayWriteContent(read, operator)).toBe(false);
  });
});

describe("useGlobalCreateAccess", () => {
  it("is false for both when every guild is frozen or read-only-granted", () => {
    mockUseAuth.mockReturnValue({ user: buildUser({ role: "member" }) });
    mockUseGuilds.mockReturnValue({
      guilds: [memberGuild({ id: 1, content_read_only: true }), grantEntry("read")],
    });

    const { result } = renderHook(() => useGlobalCreateAccess());
    expect(result.current).toEqual({ document: false, task: false });
  });

  it("separates authoring from writing for a scoped read_write grant", () => {
    // Only guild is a scoped read_write grant: can create tasks (write) but not
    // author documents.
    mockUseAuth.mockReturnValue({ user: buildUser({ role: "member" }) });
    mockUseGuilds.mockReturnValue({ guilds: [grantEntry("read_write")] });

    const { result } = renderHook(() => useGlobalCreateAccess());
    expect(result.current).toEqual({ document: false, task: true });
  });

  it("is true for both when a member guild is present", () => {
    mockUseAuth.mockReturnValue({ user: buildUser({ role: "member" }) });
    mockUseGuilds.mockReturnValue({ guilds: [memberGuild()] });

    const { result } = renderHook(() => useGlobalCreateAccess());
    expect(result.current).toEqual({ document: true, task: true });
  });
});

describe("useInitiativeAccess canManage", () => {
  const asMember = (user: ReturnType<typeof buildUser>) => {
    mockUseAuth.mockReturnValue({ user });
    mockUseGuilds.mockReturnValue({ activeGuild: { id: 1, role: "member" } });
  };

  /** One initiative, with this user holding the given role. */
  const withRole = (
    user: ReturnType<typeof buildUser>,
    role: Partial<ReturnType<typeof buildInitiativeMember>>
  ) =>
    buildInitiative({
      members: [
        buildInitiativeMember({
          user: { id: user.id, full_name: user.full_name, email: user.email },
          ...role,
        }),
      ],
    });

  it("counts the built-in managing role", () => {
    const user = buildUser();
    asMember(user);
    const initiative = withRole(user, {
      role: "project_manager",
      role_name: "project_manager",
      is_manager: true,
    });

    const { result } = renderHook(() => useInitiativeAccess());
    expect(result.current.canManage(initiative)).toBe(true);
  });

  it("counts a managing role the initiative named itself", () => {
    // An initiative that renamed its managers, or added a second managing
    // role: the flag is what the server reads, and the legacy `role` field
    // reports `member` for anything but the built-in name.
    const user = buildUser();
    asMember(user);
    const initiative = withRole(user, {
      role: "member",
      role_name: "lead",
      role_display_name: "Lead",
      is_manager: true,
    });

    const { result } = renderHook(() => useInitiativeAccess());
    expect(result.current.canManage(initiative)).toBe(true);
  });

  it("does not count an ordinary member", () => {
    const user = buildUser();
    asMember(user);

    const { result } = renderHook(() => useInitiativeAccess());
    expect(result.current.canManage(withRole(user, { is_manager: false }))).toBe(false);
  });

  it("does not count managing some other initiative", () => {
    const user = buildUser();
    asMember(user);
    const elsewhere = buildInitiative({
      members: [buildInitiativeMember({ is_manager: true })],
    });

    const { result } = renderHook(() => useInitiativeAccess());
    expect(result.current.canManage(elsewhere)).toBe(false);
  });

  it("counts a guild admin everywhere", () => {
    const user = buildUser();
    mockUseAuth.mockReturnValue({ user });
    mockUseGuilds.mockReturnValue({ activeGuild: { id: 1, role: "admin" } });

    const { result } = renderHook(() => useInitiativeAccess());
    expect(result.current.canManage(buildInitiative({ members: [] }))).toBe(true);
  });
});
