import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { buildInitiative, buildUser } from "@/__tests__/factories";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { useInitiativeAccess } from "@/hooks/useInitiativeAccess";

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
