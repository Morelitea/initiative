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

/**
 * Capture every GET /calendar-entries/ and serve one union payload. The
 * aggregate returns events + all in-window tasks in a single request, so there
 * is no per-page walking to stub.
 */
function stubEntries(
  { events = [], tasks = [] }: { events?: unknown[]; tasks?: unknown[] },
  projects = [buildProject({ id: PROJECT_ID, initiative_id: INITIATIVE_ID, name: "Apollo" })]
) {
  const requests: URLSearchParams[] = [];
  server.use(
    guildHttp.get("/calendar-entries/", ({ request }) => {
      requests.push(new URL(request.url).searchParams);
      return HttpResponse.json({ events, tasks });
    }),
    guildHttp.get("/projects/", () =>
      HttpResponse.json({
        items: projects,
        total_count: projects.length,
        page: 1,
        page_size: 0,
        has_next: false,
      })
    )
  );
  return requests;
}

const parseConditions = (params: URLSearchParams) =>
  JSON.parse(params.get("conditions") ?? "[]") as (FilterCondition | FilterGroup)[];

const isGroup = (c: FilterCondition | FilterGroup): c is FilterGroup => "conditions" in c;

describe("EventsView calendar-entries query", () => {
  it("issues a single calendar-entries request windowed to the dates the view renders", async () => {
    const requests = stubEntries({ tasks: [] });

    renderEvents();

    await waitFor(() => expect(requests.length).toBeGreaterThan(0));

    // The window bounds BOTH legs via start_after/start_before — the endpoint
    // windows events and tasks by these, so the date range isn't duplicated
    // inside `conditions`. List view shows the focus month exactly.
    const now = new Date();
    expect(requests[0].get("start_after")).toBe(startOfMonth(now).toISOString());
    expect(requests[0].get("start_before")).toBe(endOfMonth(now).toISOString());

    // `conditions` carries only the non-window filters (none selected here), so
    // it never contains a start_date/due_date group.
    const groups = parseConditions(requests[0]).filter(isGroup);
    expect(groups).toHaveLength(0);
  });

  it("renders every in-window task the aggregate returns", async () => {
    // The aggregate returns all in-window tasks in one payload; the page used to
    // walk paginated /tasks and silently drop anything past the hundredth.
    const tasks = Array.from({ length: 101 }, (_, i) =>
      buildTask({
        id: i + 1,
        title: i === 100 ? "Hundred and first task" : `Task ${i + 1}`,
        project_id: PROJECT_ID,
        due_date: inFocusMonth(i % 27),
      })
    );
    stubEntries({ tasks });

    renderEvents();

    expect(await screen.findByText("Hundred and first task")).toBeInTheDocument();
    expect(screen.getByText("Task 1")).toBeInTheDocument();
  });

  it("offers the initiative's projects as filter options, whatever the window holds", async () => {
    // No task in the window belongs to Apollo — its option has to survive
    // anyway, or the filter would vanish on any month the project is quiet.
    stubEntries({ tasks: [] }, [
      buildProject({ id: PROJECT_ID, initiative_id: INITIATIVE_ID, name: "Apollo" }),
      buildProject({ id: 2, initiative_id: INITIATIVE_ID, name: "Zeus" }),
      buildProject({
        id: 3,
        initiative_id: INITIATIVE_ID,
        name: "A template",
        is_template: true,
      }),
      buildProject({ id: 4, initiative_id: 99, name: "Another initiative's" }),
    ]);

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
