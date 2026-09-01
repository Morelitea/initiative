import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { buildProject, resetFactories } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import { ProjectSettingsDetailsTab } from "@/components/projects/settings/ProjectSettingsDetailsTab";

const renderTab = (project: ReturnType<typeof buildProject>) =>
  renderWithProviders(
    <ProjectSettingsDetailsTab project={project} projectId={project.id} canWriteProject />
  );

const nameField = () => screen.getByLabelText("Name") as HTMLInputElement;

describe("ProjectSettingsDetailsTab seeding", () => {
  beforeEach(() => {
    resetFactories();
  });

  it("fills the form from the project", () => {
    renderTab(buildProject({ name: "Roadmap", start_date: "2026-03-02" }));

    expect(nameField().value).toBe("Roadmap");
  });

  it("picks up a change made elsewhere while the form sits untouched", () => {
    const project = buildProject({ name: "Roadmap" });
    const { rerender } = renderTab(project);

    // Same project, refetched after someone else renamed it.
    rerender(
      <ProjectSettingsDetailsTab
        project={{ ...project, name: "Renamed elsewhere" }}
        projectId={project.id}
        canWriteProject
      />
    );

    expect(nameField().value).toBe("Renamed elsewhere");
  });

  it("keeps unsaved typing when a background refetch arrives", async () => {
    const user = userEvent.setup();
    const project = buildProject({ name: "Roadmap" });
    const { rerender } = renderTab(project);

    await user.clear(nameField());
    await user.type(nameField(), "My unsaved edit");

    rerender(
      <ProjectSettingsDetailsTab
        project={{ ...project, name: "Renamed elsewhere" }}
        projectId={project.id}
        canWriteProject
      />
    );

    expect(nameField().value).toBe("My unsaved edit");
  });

  it("reseeds when the tab moves to a different project, edits or not", async () => {
    const user = userEvent.setup();
    const project = buildProject({ name: "Roadmap" });
    const { rerender } = renderTab(project);

    await user.clear(nameField());
    await user.type(nameField(), "My unsaved edit");

    const other = buildProject({ name: "Other project" });
    rerender(<ProjectSettingsDetailsTab project={other} projectId={other.id} canWriteProject />);

    expect(nameField().value).toBe("Other project");
  });

  it("blocks the save while the dates are inverted", async () => {
    renderTab(buildProject({ start_date: "2026-09-30", end_date: "2026-03-02" }));

    expect(screen.getByText("The end date can't be before the start date.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
  });

  it("allows the save for an ordered range", () => {
    renderTab(buildProject({ start_date: "2026-03-02", end_date: "2026-09-30" }));

    expect(screen.getByRole("button", { name: "Save changes" })).toBeEnabled();
  });
});
