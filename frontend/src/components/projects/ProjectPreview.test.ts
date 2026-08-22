import { describe, expect, it } from "vitest";

import {
  buildInitiative,
  buildInitiativeMember,
  buildProject,
  buildUserPublic,
} from "@/__tests__/factories";
import type { InitiativeMemberRead } from "@/api/generated/initiativeAPI.schemas";
import { canPinProject } from "@/components/projects/ProjectPreview";

const USER_ID = 7;

/** A project whose initiative has this user holding the given role. */
const projectWithRole = (role: Partial<InitiativeMemberRead>) =>
  buildProject({
    initiative: buildInitiative({
      members: [buildInitiativeMember({ user: buildUserPublic({ id: USER_ID }), ...role })],
    }),
  });

describe("canPinProject", () => {
  it("counts the built-in managing role", () => {
    const project = projectWithRole({ role_name: "project_manager", is_manager: true });
    expect(canPinProject(project, USER_ID)).toBe(true);
  });

  it("refuses an archived project, whoever is asking", () => {
    // The server rejects every edit to an archived project, pinning included,
    // so the card must not offer it.
    const managed = projectWithRole({ role_name: "project_manager", is_manager: true });
    const archived = { ...managed, is_archived: true };
    expect(canPinProject(archived, USER_ID)).toBe(false);
    expect(canPinProject(archived, USER_ID, "admin")).toBe(false);
  });

  it("counts a managing role the initiative named itself", () => {
    // The flag is what the server reads, not the role's name: an initiative
    // that renamed its managers, or added a second managing role, still has
    // managers here.
    const project = projectWithRole({
      role_name: "lead",
      role_display_name: "Lead",
      is_manager: true,
    });
    expect(canPinProject(project, USER_ID)).toBe(true);
  });

  it("does not count an ordinary member", () => {
    const project = projectWithRole({ role_name: "member", is_manager: false });
    expect(canPinProject(project, USER_ID)).toBe(false);
  });

  it("counts a guild admin, member row or not", () => {
    const project = buildProject({ initiative: buildInitiative({ members: [] }) });
    expect(canPinProject(project, USER_ID, "admin")).toBe(true);
  });

  it("counts nobody when signed out", () => {
    const project = projectWithRole({ is_manager: true });
    expect(canPinProject(project, undefined, "admin")).toBe(false);
  });
});
