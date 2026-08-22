/**
 * The control that replaced the projects page's second row of tabs. Its whole
 * job is to be visible: all three states on screen with their totals, so the
 * reader can see that templates and archived projects exist without opening
 * anything. The Radix default of clearing a single-select group on a second
 * click would leave the list with no state at all, so that is pinned down too.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ProjectStatusFilter } from "@/components/projects/ProjectStatusFilter";

describe("ProjectStatusFilter", () => {
  it("shows every state with its total", () => {
    render(
      <ProjectStatusFilter
        value="active"
        onChange={vi.fn()}
        counts={{ active: 8, templates: 3, archived: 5 }}
      />
    );

    for (const [label, count] of [
      ["Active", "8"],
      ["Templates", "3"],
      ["Archived", "5"],
    ]) {
      const option = screen.getByRole("radio", { name: new RegExp(label) });
      expect(option).toHaveTextContent(count);
    }
    expect(screen.getByRole("radio", { name: /Active/ })).toHaveAttribute("data-state", "on");
  });

  it("renders without totals before they load", () => {
    render(<ProjectStatusFilter value="templates" onChange={vi.fn()} />);
    expect(screen.getByRole("radio", { name: "Templates" })).toHaveAttribute("data-state", "on");
  });

  it("reports the state the reader picked", async () => {
    const onChange = vi.fn();
    render(<ProjectStatusFilter value="active" onChange={onChange} counts={{ archived: 5 }} />);

    await userEvent.click(screen.getByRole("radio", { name: /Archived/ }));
    expect(onChange).toHaveBeenCalledWith("archived");
  });

  it("keeps the current state when it is clicked again", async () => {
    const onChange = vi.fn();
    render(<ProjectStatusFilter value="active" onChange={onChange} />);

    await userEvent.click(screen.getByRole("radio", { name: "Active" }));
    expect(onChange).not.toHaveBeenCalled();
  });
});
