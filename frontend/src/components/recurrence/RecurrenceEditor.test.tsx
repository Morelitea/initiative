/**
 * What the Repeat field says, and the dates it shows.
 *
 * The summary line under the preset select restated the select's own value:
 * an untouched form read "Does not repeat" twice over. It now appears only
 * once there is a real rule for it to describe, with the next dates from the
 * server beneath it.
 */
import { screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import { RecurrenceEditor } from "@/components/recurrence/RecurrenceEditor";
import { createRecurrenceFromPreset, type RecurrenceRule } from "@/lib/recurrence";

const renderEditor = (value: RecurrenceRule | "custom" | null, referenceDate?: string) =>
  renderWithProviders(
    <RecurrenceEditor
      kind="event"
      value={value}
      onChange={() => {}}
      referenceDate={referenceDate ?? null}
      allDay
      stored={value === "custom" ? { rule: "RRULE:FREQ=HOURLY", shift: 0 } : null}
    />
  );

describe("RecurrenceEditor", () => {
  it("says 'Does not repeat' once, in the select, when there is no rule", async () => {
    renderEditor(null);

    // The select still carries the label; what is gone is the paragraph under
    // it that used to repeat the same words.
    expect(await screen.findAllByText(/does not repeat/i)).toHaveLength(1);
  });

  it("summarises a real rule beneath the select", async () => {
    renderEditor({
      ...(createRecurrenceFromPreset("daily") as RecurrenceRule),
      frequency: "weekly",
      interval: 2,
      weekdays: ["monday"],
    });

    expect(await screen.findByText(/every 2 weeks/i)).toBeInTheDocument();
    expect(screen.queryByText(/does not repeat/i)).not.toBeInTheDocument();
  });

  it("shows the next dates the server gives, for a rule it can't build too", async () => {
    let asked: Record<string, unknown> | undefined;
    server.use(
      http.post("/api/v1/recurrence/preview", async ({ request }) => {
        asked = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({
          rule: asked.rule,
          shift: 0,
          occurrences: ["2026-10-05T00:00:00Z", "2026-10-06T00:00:00Z"],
        });
      })
    );
    renderEditor("custom", "2026-10-05T09:00:00");

    expect(await screen.findByText(/oct 5, 2026 · oct 6, 2026/i)).toBeInTheDocument();
    // The stored rule, with its own shift, from the all-day event's date.
    expect(asked).toMatchObject({
      rule: "RRULE:FREQ=HOURLY",
      shift: 0,
      start: "2026-10-05T00:00:00Z",
    });
  });
});
