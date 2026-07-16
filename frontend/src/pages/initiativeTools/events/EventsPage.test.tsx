import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { endOfMonth, startOfMonth } from "date-fns";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { buildProject, buildTask } from "@/__tests__/factories";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { createTestQueryClient, renderPage } from "@/__tests__/helpers/render";
import type { FilterCondition, FilterGroup } from "@/api/generated/initiativeAPI.schemas";
import { CALENDAR_VIEW_MODE_KEY } from "@/components/calendar";
import { VIEW_PREFERENCES_QUERY_KEY } from "@/hooks/useViewPreference";

import { EventsView } from "./EventsPage";

const INITIATIVE_ID = 1;
const PROJECT_ID = 1;

/** A day comfortably inside the focus month, so it lands in every view. */
const inFocusMonth = (dayOffset: number) => {
  const d = startOfMonth(new Date());
  d.setDate(d.getDate() + dayOffset);
  d.setHours(12, 0, 0, 0);
  return d.toISOString();
};

/**
 * Render the calendar in list view — the list renders a row per entry, so a
 * task either appears or it doesn't. The month grid collapses a busy day into
 * "+N more", which would hide the very thing these tests check for.
 */
function renderEvents() {
  const queryClient = createTestQueryClient();
  queryClient.setQueryData(VIEW_PREFERENCES_QUERY_KEY, {
    items: { [CALENDAR_VIEW_MODE_KEY]: "list" },
  });
  const Page = () => <EventsView fixedInitiativeId={INITIATIVE_ID} canCreate={false} />;
  return renderPage(Page, { queryClient });
}

/** Capture the params of every GET /tasks/ and serve `pages` in order. */
function stubTaskPages(
  pages: { items: unknown[]; has_next: boolean }[],
  projects = [buildProject({ id: PROJECT_ID, initiative_id: INITIATIVE_ID, name: "Apollo" })]
) {
  const requests: URLSearchParams[] = [];
  server.use(
    guildHttp.get("/calendar-events/", () =>
      HttpResponse.json({
        items: [],
        total_count: 0,
        page: 1,
        page_size: 0,
        has_next: false,
        has_prev: false,
      })
    ),
    guildHttp.get("/projects/", () =>
      HttpResponse.json({
        items: projects,
        total_count: projects.length,
        page: 1,
        page_size: 0,
        has_next: false,
      })
    ),
    guildHttp.get("/tasks/", ({ request }) => {
      const params = new URL(request.url).searchParams;
      requests.push(params);
      const page = Number(params.get("page") ?? 1);
      const body = pages[page - 1] ?? { items: [], has_next: false };
      return HttpResponse.json({
        ...body,
        total_count: pages.reduce((n, p) => n + p.items.length, 0),
        page,
        page_size: 0,
        has_prev: page > 1,
        sorting: null,
      });
    })
  );
  return requests;
}

const parseConditions = (params: URLSearchParams) =>
  JSON.parse(params.get("conditions") ?? "[]") as (FilterCondition | FilterGroup)[];

const isGroup = (c: FilterCondition | FilterGroup): c is FilterGroup => "conditions" in c;

describe("EventsView tasks query", () => {
  it("windows the tasks query to the dates the view renders", async () => {
    const requests = stubTaskPages([{ items: [], has_next: false }]);

    renderEvents();

    await waitFor(() => expect(requests.length).toBeGreaterThan(0));

    const group = parseConditions(requests[0]).find(isGroup);
    expect(group).toBeDefined();
    expect(group?.logic).toBe("or");

    // A task sits on the calendar by its start_date, its due_date, or both, so
    // the window must match either — not both at once.
    const legs = (group?.conditions ?? []).filter(isGroup);
    expect(legs).toHaveLength(2);
    const fields = legs.map((leg) => (leg.conditions[0] as FilterCondition).field);
    expect(fields).toEqual(["start_date", "due_date"]);

    // List view shows the focus month exactly.
    const now = new Date();
    for (const leg of legs) {
      const [gte, lte] = leg.conditions as FilterCondition[];
      expect(leg.logic).toBe("and");
      expect(gte.op).toBe("gte");
      expect(gte.value).toBe(startOfMonth(now).toISOString());
      expect(lte.op).toBe("lte");
      expect(lte.value).toBe(endOfMonth(now).toISOString());
    }
  });

  it("renders every in-window task when the results span more than one page", async () => {
    // The old query asked for a flat page_size=100 and took page 1 only, so
    // anything past the hundredth in-window task silently vanished.
    const page1 = Array.from({ length: 100 }, (_, i) =>
      buildTask({
        id: i + 1,
        title: `Task ${i + 1}`,
        project_id: PROJECT_ID,
        due_date: inFocusMonth(i % 27),
      })
    );
    const page2 = [
      buildTask({
        id: 101,
        title: "Hundred and first task",
        project_id: PROJECT_ID,
        due_date: inFocusMonth(3),
      }),
    ];
    const requests = stubTaskPages([
      { items: page1, has_next: true },
      { items: page2, has_next: false },
    ]);

    renderEvents();

    // The task beyond the old cap is on the calendar.
    expect(await screen.findByText("Hundred and first task")).toBeInTheDocument();
    expect(screen.getByText("Task 1")).toBeInTheDocument();

    // page_size=0 asks for whole windows, and both were walked.
    await waitFor(() => expect(requests).toHaveLength(2));
    expect(requests[0].get("page_size")).toBe("0");
    expect(requests.map((r) => r.get("page"))).toEqual(["1", "2"]);
  });

  it("offers the initiative's projects as filter options, whatever the window holds", async () => {
    // No task in the window belongs to Apollo — its option has to survive
    // anyway, or the filter would vanish on any month the project is quiet.
    stubTaskPages(
      [{ items: [], has_next: false }],
      [
        buildProject({ id: PROJECT_ID, initiative_id: INITIATIVE_ID, name: "Apollo" }),
        buildProject({ id: 2, initiative_id: INITIATIVE_ID, name: "Zeus" }),
        buildProject({
          id: 3,
          initiative_id: INITIATIVE_ID,
          name: "A template",
          is_template: true,
        }),
        buildProject({ id: 4, initiative_id: 99, name: "Another initiative's" }),
      ]
    );

    const user = userEvent.setup();
    renderEvents();

    // The label isn't bound to the Radix trigger, so scope by their shared row.
    const label = await screen.findByText("Project");
    const trigger = within(label.parentElement as HTMLElement).getByRole("combobox");
    await user.click(trigger);

    expect(await screen.findByText("Apollo")).toBeInTheDocument();
    expect(screen.getByText("Zeus")).toBeInTheDocument();
    // Templates are held out of the calendar's tasks, and other initiatives
    // aren't in scope at all.
    expect(screen.queryByText("A template")).toBeNull();
    expect(screen.queryByText("Another initiative's")).toBeNull();
  });
});
