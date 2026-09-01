import { screen, waitFor } from "@testing-library/react";
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

import { CalendarsView } from "./CalendarsPage";

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
function renderCalendars() {
  const queryClient = createTestQueryClient();
  queryClient.setQueryData(VIEW_PREFERENCES_QUERY_KEY, {
    items: { [CALENDAR_VIEW_MODE_KEY]: "list" },
  });
  const Page = () => <CalendarsView fixedInitiativeId={INITIATIVE_ID} canCreate={false} />;
  return renderPage(Page, { queryClient });
}

/**
 * Capture every GET /calendar-entries/ and serve one union payload. The
 * aggregate returns events + all in-window tasks in a single request, so there
 * is no per-page walking to stub. The page also lists the initiative's real
 * calendars for its panel; serve an empty set unless a test provides one.
 */
function stubEntries(
  { events = [], tasks = [] }: { events?: unknown[]; tasks?: unknown[] },
  projects = [buildProject({ id: PROJECT_ID, initiative_id: INITIATIVE_ID, name: "Apollo" })],
  calendars: unknown[] = []
) {
  const requests: URLSearchParams[] = [];
  server.use(
    guildHttp.get("/calendar-entries/", ({ request }) => {
      requests.push(new URL(request.url).searchParams);
      return HttpResponse.json({ events, tasks });
    }),
    guildHttp.get("/calendars/", () =>
      HttpResponse.json({
        items: calendars,
        total_count: calendars.length,
        page: 1,
        page_size: 100,
        has_next: false,
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
    )
  );
  return requests;
}

const parseConditions = (params: URLSearchParams) =>
  JSON.parse(params.get("conditions") ?? "[]") as (FilterCondition | FilterGroup)[];

const isGroup = (c: FilterCondition | FilterGroup): c is FilterGroup => "conditions" in c;

describe("CalendarsView calendar-entries query", () => {
  it("issues a single calendar-entries request windowed to the dates the view renders", async () => {
    const requests = stubEntries({ tasks: [] });

    renderCalendars();

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

    renderCalendars();

    expect(await screen.findByText("Hundred and first task")).toBeInTheDocument();
    expect(screen.getByText("Task 1")).toBeInTheDocument();
  });

  it("lists a task calendar per project with in-window tasks and hides its tasks when toggled off", async () => {
    // The panel derives one read-only calendar per project FROM the tasks
    // payload — a project with no task in the window gets no row.
    stubEntries(
      {
        tasks: [
          buildTask({
            id: 1,
            title: "Apollo task",
            project_id: PROJECT_ID,
            due_date: inFocusMonth(3),
          }),
        ],
      },
      [
        buildProject({ id: PROJECT_ID, initiative_id: INITIATIVE_ID, name: "Apollo" }),
        buildProject({ id: 2, initiative_id: INITIATIVE_ID, name: "Zeus" }),
      ]
    );

    const user = userEvent.setup();
    renderCalendars();

    expect(await screen.findByText("Apollo task")).toBeInTheDocument();

    // The visibility panel lives behind the filter bar's Calendars dropdown.
    await user.click(screen.getByRole("button", { name: /calendars/i }));
    // Only Apollo has a task in the window, so only it gets a panel row.
    expect(await screen.findByRole("checkbox", { name: "Apollo" })).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "Zeus" })).toBeNull();

    // Unchecking the project's calendar hides its tasks from the view.
    await user.click(screen.getByRole("checkbox", { name: "Apollo" }));
    await waitFor(() => expect(screen.queryByText("Apollo task")).toBeNull());
  });
});

describe("CalendarsView on a guild calendar", () => {
  /** The calendar the app mounts: guild-level, so it belongs to no initiative. */
  const guildCalendar = {
    id: 42,
    name: "Guild calendar",
    description: null,
    color: "#6366f1",
    initiative_id: null,
    guild_id: 1,
    created_by: 1,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    my_permission_level: "write",
    tags: [],
    grants: [],
  };

  it("asks for its own events only, and reads nothing initiative-shaped", async () => {
    const entries: URLSearchParams[] = [];
    const calendarList: string[] = [];
    const projectList: string[] = [];
    server.use(
      guildHttp.get("/calendar-entries/", ({ request }) => {
        entries.push(new URL(request.url).searchParams);
        return HttpResponse.json({ events: [], tasks: [] });
      }),
      guildHttp.get("/calendars/", ({ request }) => {
        calendarList.push(request.url);
        return HttpResponse.json({
          items: [],
          total_count: 0,
          page: 1,
          page_size: 100,
          has_next: false,
        });
      }),
      guildHttp.get("/projects/", ({ request }) => {
        projectList.push(request.url);
        return HttpResponse.json({
          items: [],
          total_count: 0,
          page: 1,
          page_size: 0,
          has_next: false,
        });
      })
    );

    const queryClient = createTestQueryClient();
    queryClient.setQueryData(VIEW_PREFERENCES_QUERY_KEY, {
      items: { [CALENDAR_VIEW_MODE_KEY]: "list" },
    });
    const Page = () => <CalendarsView soloCalendar={guildCalendar} />;
    renderPage(Page, { queryClient });

    await waitFor(() => expect(entries.length).toBeGreaterThan(0));

    // Exactly this calendar, no task leg, and no initiative to narrow to.
    expect(entries[0].getAll("calendar_ids")).toEqual([String(guildCalendar.id)]);
    expect(entries[0].get("include_tasks")).toBe("false");
    expect(entries[0].get("initiative_id")).toBeNull();

    // The panel, the task-calendar rows and the filter bar are all initiative-
    // shaped, so the surface never lists the guild's calendars or projects.
    expect(calendarList).toEqual([]);
    expect(projectList).toEqual([]);
  });
});

describe("CalendarsView on the calendar app's own surface", () => {
  const guildCalendar = (id: number, name: string) => ({
    id,
    name,
    description: null,
    color: "#6366f1",
    initiative_id: null,
    guild_id: 1,
    created_by: 1,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    my_permission_level: "write",
    tags: [],
    grants: [],
  });

  /** Serve the guild's calendars, recording what the page asked for. */
  function stubGuildScope(calendars: ReturnType<typeof guildCalendar>[], events: unknown[] = []) {
    const entries: URLSearchParams[] = [];
    const calendarList: URLSearchParams[] = [];
    const projectList: string[] = [];
    server.use(
      guildHttp.get("/calendar-entries/", ({ request }) => {
        entries.push(new URL(request.url).searchParams);
        return HttpResponse.json({ events, tasks: [] });
      }),
      guildHttp.get("/calendars/", ({ request }) => {
        calendarList.push(new URL(request.url).searchParams);
        return HttpResponse.json({
          items: calendars,
          total_count: calendars.length,
          page: 1,
          page_size: 200,
          has_next: false,
        });
      }),
      guildHttp.get("/projects/", ({ request }) => {
        projectList.push(request.url);
        return HttpResponse.json({
          items: [],
          total_count: 0,
          page: 1,
          page_size: 0,
          has_next: false,
        });
      })
    );
    return { entries, calendarList, projectList };
  }

  function renderGuildScope() {
    const queryClient = createTestQueryClient();
    queryClient.setQueryData(VIEW_PREFERENCES_QUERY_KEY, {
      items: { [CALENDAR_VIEW_MODE_KEY]: "list" },
    });
    return renderPage(() => <CalendarsView guildScope />, { queryClient });
  }

  it("asks for the guild's own calendars and overlays all of them", async () => {
    const { entries, calendarList, projectList } = stubGuildScope([
      guildCalendar(42, "Holidays"),
      guildCalendar(43, "Game nights"),
    ]);

    renderGuildScope();

    await waitFor(() => expect(entries.length).toBeGreaterThan(0));

    // The list is asked for by scope, not inferred from an absent initiative —
    // otherwise it would answer with every initiative's calendars too.
    expect(calendarList[0].get("scope")).toBe("guild");
    // The events are asked for by scope too, rather than by naming the
    // calendars: the list above is one page of them, and an event on a calendar
    // past the end of it would simply not be drawn.
    expect(entries[0].get("scope")).toBe("guild");
    expect(entries[0].getAll("calendar_ids")).toEqual([]);
    expect(entries[0].get("include_tasks")).toBe("false");
    expect(entries[0].get("initiative_id")).toBeNull();
    // Projects are task-shaped, and this surface holds no tasks.
    expect(projectList).toEqual([]);
  });

  it("lets a reader hide one of them", async () => {
    stubGuildScope(
      [guildCalendar(42, "Holidays"), guildCalendar(43, "Game nights")],
      [
        {
          id: 1,
          calendar_id: 42,
          title: "Midsummer",
          description: null,
          start_at: inFocusMonth(3),
          end_at: inFocusMonth(3),
          all_day: true,
          attendee_previews: [],
          property_values: [],
          tags: [],
          my_permission_level: "write",
        },
      ]
    );

    const user = userEvent.setup();
    renderGuildScope();

    expect(await screen.findByText("Midsummer")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /calendars/i }));
    await user.click(await screen.findByRole("checkbox", { name: "Holidays" }));
    await waitFor(() => expect(screen.queryByText("Midsummer")).toBeNull());
  });

  it("puts the picker and the way to add a calendar on the page, not behind the filter button", async () => {
    stubGuildScope([guildCalendar(42, "Holidays"), guildCalendar(43, "Game nights")]);

    renderGuildScope();

    // The picker rides the toolbar row: this surface has no other filter, so
    // there is no disclosure to open before reaching it.
    expect(await screen.findByRole("button", { name: /calendars/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /filters/i })).toBeNull();
    // Adding a calendar is offered on a populated surface too, not only from
    // the empty state.
    expect(screen.getByRole("button", { name: /new calendar/i })).toBeInTheDocument();
  });

  it("says how many calendars are switched off while the picker is shut", async () => {
    stubGuildScope([guildCalendar(42, "Holidays"), guildCalendar(43, "Game nights")]);

    const user = userEvent.setup();
    renderGuildScope();

    await user.click(await screen.findByRole("button", { name: /calendars/i }));
    await user.click(await screen.findByRole("checkbox", { name: "Holidays" }));
    await user.keyboard("{Escape}");

    expect(await screen.findByRole("button", { name: /1 calendar hidden/i })).toBeInTheDocument();
  });

  it("offers to make the first one rather than showing an empty grid", async () => {
    stubGuildScope([]);

    renderGuildScope();

    expect(await screen.findByText(/no calendars yet/i)).toBeInTheDocument();
    // Any member may add one, so the offer stands without an initiative role.
    expect(screen.getAllByRole("button", { name: /new calendar/i }).length).toBeGreaterThan(0);
  });
});
