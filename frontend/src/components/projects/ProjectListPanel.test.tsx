/**
 * Bulk sharing across the three project states. The Templates and Archive
 * lists gained bulk select when they started rendering through this panel —
 * and the server refuses a sharing change on an archived project, so offering
 * the action there would only fail at submit.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { buildProject } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import { ProjectListPanel } from "@/components/projects/ProjectListPanel";

const panel = (projects: ReturnType<typeof buildProject>[]) =>
  renderPage(() => (
    <ProjectListPanel
      projects={projects}
      isLoading={false}
      isError={false}
      loadingLabel="Loading"
      errorLabel="Error"
      noMatchesLabel="No matches"
      emptyState={<p>Empty</p>}
      storagePrefix="project:test"
    />
  ));

const selectProject = async (name: string) => {
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: /select/i }));
  await user.click(await screen.findByRole("button", { name, pressed: false }));
};

describe("ProjectListPanel bulk sharing", () => {
  it("offers sharing on an ordinary selection", async () => {
    panel([buildProject({ name: "Barovia Arc", my_permission_level: "owner" })]);

    await selectProject("Barovia Arc");

    expect(screen.getByRole("button", { name: /edit access/i })).toBeEnabled();
  });

  it("refuses sharing on an archived selection, and says why", async () => {
    panel([
      buildProject({
        name: "Planescape Detour",
        my_permission_level: "owner",
        is_archived: true,
        archived_at: "2026-06-01T00:00:00.000Z",
      }),
    ]);

    await selectProject("Planescape Detour");

    const editAccess = screen.getByRole("button", { name: /edit access/i });
    expect(editAccess).toBeDisabled();
    expect(editAccess).toHaveAttribute("title", "Sharing can't be changed on an archived project.");
  });
});
