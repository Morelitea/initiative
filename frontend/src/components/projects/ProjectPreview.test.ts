import { describe, expect, it } from "vitest";

import { buildProject } from "@/__tests__/factories";
import { canPinProject } from "@/components/projects/ProjectPreview";

const USER_ID = 7;

describe("canPinProject", () => {
  it("offers the pin wherever the server says the reader may configure the project", () => {
    // Who that is — a guild admin, a manager of the initiative, the project's
    // owner — is settled on the server and arrives as one flag.
    expect(canPinProject(buildProject({ can_configure: true }), USER_ID)).toBe(true);
  });

  it("does not offer it where the server says no", () => {
    expect(canPinProject(buildProject({ can_configure: false }), USER_ID)).toBe(false);
  });

  it("refuses an archived project, whoever is asking", () => {
    // The server rejects every edit to an archived project, pinning included,
    // so the card must not offer it.
    const archived = buildProject({
      can_configure: true,
      archived_at: "2026-06-01T00:00:00.000Z",
    });
    expect(canPinProject(archived, USER_ID)).toBe(false);
  });

  it("counts nobody when signed out", () => {
    expect(canPinProject(buildProject({ can_configure: true }), undefined)).toBe(false);
  });
});
