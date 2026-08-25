import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ToolListToolbar } from "./ToolListToolbar";

describe("ToolListToolbar heading", () => {
  it("keeps the heading on the control row, in a container that still wraps", () => {
    render(
      <ToolListToolbar
        heading={<h2>Project tasks</h2>}
        filters={{ open: false, onOpenChange: () => {}, activeCount: 0 }}
      />
    );

    const heading = screen.getByRole("heading", { name: "Project tasks" });
    const filterButton = screen.getByRole("button", { name: /filters/i });

    // Same flex row: the heading's wrapper and the controls' group are siblings
    // inside the toolbar, rather than the heading sitting on a line above it.
    const row = heading.parentElement?.parentElement;
    expect(row).toBe(filterButton.parentElement?.parentElement);
    // Wrapping is what lets the controls drop to a second line when the row
    // runs out of room instead of squeezing against the heading.
    expect(row).toHaveClass("flex-wrap");
  });

  it("renders no heading container when the list has no heading", () => {
    render(<ToolListToolbar filters={{ open: false, onOpenChange: () => {} }} />);

    expect(screen.queryByRole("heading")).not.toBeInTheDocument();
  });
});
