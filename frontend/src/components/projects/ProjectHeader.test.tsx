import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { buildProject, resetFactories } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import { ProjectOverviewCard } from "@/components/projects/ProjectOverviewCard";

const renderCard = (dates: { start_date?: string | null; end_date?: string | null }) =>
  renderWithProviders(
    <ProjectOverviewCard project={buildProject(dates)} projectIsArchived={false} />
  );

describe("ProjectOverviewCard schedule", () => {
  beforeEach(() => {
    resetFactories();
  });

  it("shows both dates when the project has a start and an end", () => {
    renderCard({ start_date: "2026-03-02", end_date: "2026-09-30" });

    expect(screen.getByText("Mar 2, 2026 – Sep 30, 2026")).toBeInTheDocument();
  });

  it("renders a date-only value as that calendar day, not the day before", () => {
    // A bare YYYY-MM-DD parsed as UTC would render Mar 1 west of Greenwich.
    renderCard({ start_date: "2026-03-02" });

    expect(screen.getByText("Starts Mar 2, 2026")).toBeInTheDocument();
  });

  it("shows only the end when that is all the project has", () => {
    renderCard({ end_date: "2026-09-30" });

    expect(screen.getByText("Ends Sep 30, 2026")).toBeInTheDocument();
  });

  it("shows nothing at all when neither date is set", () => {
    renderCard({});

    expect(screen.queryByText("Project dates")).not.toBeInTheDocument();
  });
});
