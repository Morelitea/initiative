import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { buildProject, resetFactories } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import { ProjectHeader } from "@/components/projects/ProjectHeader";

const renderHeader = (dates: { start_date?: string | null; end_date?: string | null }) =>
  renderPage(() => <ProjectHeader project={buildProject(dates)} projectIsArchived={false} />);

describe("ProjectHeader schedule", () => {
  beforeEach(() => {
    resetFactories();
  });

  it("shows both dates when the project has a start and an end", async () => {
    renderHeader({ start_date: "2026-03-02", end_date: "2026-09-30" });

    expect(await screen.findByText("Mar 2, 2026 – Sep 30, 2026")).toBeInTheDocument();
  });

  it("renders a date-only value as that calendar day, not the day before", async () => {
    // A bare YYYY-MM-DD parsed as UTC would render Mar 1 west of Greenwich.
    renderHeader({ start_date: "2026-03-02" });

    expect(await screen.findByText("Starts Mar 2, 2026")).toBeInTheDocument();
  });

  it("shows only the end when that is all the project has", async () => {
    renderHeader({ end_date: "2026-09-30" });

    expect(await screen.findByText("Ends Sep 30, 2026")).toBeInTheDocument();
  });

  it("shows nothing at all when neither date is set", async () => {
    renderHeader({});

    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByText("Project dates")).not.toBeInTheDocument();
  });
});
