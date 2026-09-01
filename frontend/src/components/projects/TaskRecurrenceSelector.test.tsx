/**
 * What the Repeat field says when it has nothing to say.
 *
 * The summary line under the preset select restated the select's own value:
 * an untouched form read "Does not repeat" twice over. It now appears only
 * once there is a real rule for it to describe.
 */
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import type { TaskRecurrenceOutput } from "@/api/generated/initiativeAPI.schemas";
import { TaskRecurrenceSelector } from "@/components/projects/TaskRecurrenceSelector";

const renderSelector = (recurrence: TaskRecurrenceOutput | null) =>
  renderWithProviders(
    <TaskRecurrenceSelector
      recurrence={recurrence}
      onChange={() => {}}
      strategy="fixed"
      onStrategyChange={() => {}}
      referenceDate={null}
    />
  );

describe("TaskRecurrenceSelector", () => {
  it("says 'Does not repeat' once, in the select, when there is no rule", async () => {
    renderSelector(null);

    // The select still carries the label; what is gone is the paragraph under
    // it that used to repeat the same words.
    expect(await screen.findAllByText(/does not repeat/i)).toHaveLength(1);
  });

  it("summarises a real rule beneath the select", async () => {
    renderSelector({
      frequency: "weekly",
      interval: 2,
      weekdays: ["monday"],
      ends: "never",
    } as TaskRecurrenceOutput);

    expect(await screen.findByText(/every 2 weeks/i)).toBeInTheDocument();
    expect(screen.queryByText(/does not repeat/i)).not.toBeInTheDocument();
  });
});
