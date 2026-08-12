import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildTask, buildTaskListResponse, resetFactories } from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { createTestQueryClient, renderPage } from "@/__tests__/helpers/render";
import { FocusSummary } from "@/components/tasks/FocusSummary";
import {
  FOCUS_DEFAULTS,
  FOCUS_PREFERENCES_KEY,
  type FocusPreferences,
  useFocusSummary,
} from "@/hooks/useFocusSummary";
import { VIEW_PREFERENCES_QUERY_KEY } from "@/hooks/useViewPreference";

const ME_TASKS = "/api/v1/me/tasks";

/** The pin query is the one addressing tasks by id; everything else is the rules. */
const isPinRequest = (conditions: unknown) =>
  Array.isArray(conditions) &&
  conditions.length > 0 &&
  (conditions[0] as { field?: string }).field === "id";

type Payloads = {
  rules?: ReturnType<typeof buildTaskListResponse>;
  pins?: ReturnType<typeof buildTaskListResponse>;
};

const captured: URLSearchParams[] = [];

function mockMyTasks({ rules, pins }: Payloads) {
  server.use(
    http.get(ME_TASKS, ({ request }) => {
      const params = new URL(request.url).searchParams;
      captured.push(params);
      const conditions = JSON.parse(params.get("conditions") ?? "[]");
      return HttpResponse.json(
        isPinRequest(conditions)
          ? (pins ?? buildTaskListResponse([]))
          : (rules ?? buildTaskListResponse([]))
      );
    })
  );
}

function renderFocus(prefs: Partial<FocusPreferences> = {}) {
  const queryClient = createTestQueryClient();
  queryClient.setQueryData(VIEW_PREFERENCES_QUERY_KEY, {
    items: { [FOCUS_PREFERENCES_KEY]: { ...FOCUS_DEFAULTS, ...prefs } },
  });

  const changeTaskStatus = vi.fn().mockResolvedValue(undefined);
  const Harness = () => {
    const focus = useFocusSummary();
    return (
      <FocusSummary
        focus={focus}
        activeGuildId={1}
        changeTaskStatus={changeTaskStatus}
        isUpdatingTaskStatus={false}
      />
    );
  };

  return { ...renderPage(Harness, { queryClient }), changeTaskStatus };
}

beforeEach(() => {
  resetFactories();
  captured.length = 0;
});

describe("FocusSummary", () => {
  it("lists work that needs doing and keeps today's completions visible", async () => {
    mockMyTasks({
      rules: buildTaskListResponse([
        buildTask({ id: 1, title: "Fix the deploy script", due_date: "2026-08-10T09:00:00Z" }),
        buildTask({ id: 2, title: "Review the release notes", due_date: "2026-08-11T09:00:00Z" }),
        buildTask({
          id: 3,
          title: "Ship the migration",
          completed_at: "2026-08-10T08:00:00Z",
          task_status: {
            id: 9,
            project_id: 1,
            name: "Done",
            category: "done",
            position: 3,
            is_default: false,
          },
        }),
      ]),
    });

    renderFocus();

    expect(await screen.findByText("Fix the deploy script")).toBeInTheDocument();
    expect(screen.getByText("Review the release notes")).toBeInTheDocument();

    // The completed one stays on the list rather than disappearing, and the
    // header counts it as progress.
    const completed = screen.getByText("Ship the migration");
    expect(completed).toBeInTheDocument();
    expect(completed).toHaveClass("line-through");
    expect(screen.getByText("1 of 3 done")).toBeInTheDocument();
  });

  it("asks for due-soon work, started work, urgent work, and today's completions in one query", async () => {
    mockMyTasks({});
    renderFocus({ dueWithinDays: 2, includeHighPriority: true });

    await waitFor(() => expect(captured.length).toBeGreaterThan(0));
    const conditions = JSON.parse(captured[0].get("conditions") ?? "[]");

    expect(conditions).toHaveLength(1);
    expect(conditions[0].logic).toBe("or");

    const stillOpen = {
      field: "status_category",
      op: "in_",
      value: ["backlog", "todo", "in_progress"],
    };
    const [dueLeg, startLeg, urgentLeg, doneLeg] = conditions[0].conditions;

    // Due-soon OR started OR urgent, as sibling AND legs. Two things ride on
    // this shape: an AND between date and priority would empty the list on
    // exactly the days it matters most, and a third level of nesting is
    // rejected outright by the API's group-depth cap.
    expect(dueLeg.conditions).toEqual([
      stillOpen,
      { field: "due_date", op: "lte", value: expect.any(String) },
    ]);
    expect(startLeg.conditions).toEqual([
      stillOpen,
      { field: "start_date", op: "lte", value: expect.any(String) },
    ]);
    expect(urgentLeg.conditions).toEqual([
      stillOpen,
      { field: "priority", op: "in_", value: ["urgent", "high"] },
    ]);
    expect(doneLeg.conditions).toEqual([
      { field: "status_category", op: "in_", value: ["done"] },
      { field: "completed_at", op: "gte", value: expect.any(String) },
    ]);

    // Both dates are measured to the same edge of the window, so the setting
    // means one thing rather than two.
    expect(startLeg.conditions[1].value).toBe(dueLeg.conditions[1].value);

    // The list spans every guild the user belongs to and answers only to its
    // own settings — it is not scoped by the guild you happen to be viewing,
    // nor by the task table's filters.
    expect(captured[0].get("conditions")).not.toContain("guild_id");
  });

  it("asks for backlog work too, not just what someone moved to To Do", async () => {
    // Backlog is the default status of a newly created task, so excluding it
    // empties the section on an ordinary install — overdue tasks included.
    mockMyTasks({});
    renderFocus();

    await waitFor(() => expect(captured.length).toBeGreaterThan(0));
    const conditions = JSON.parse(captured[0].get("conditions") ?? "[]");

    const openValues = conditions[0].conditions
      .flatMap((leg: { conditions: { field: string; value: unknown }[] }) => leg.conditions)
      .filter((c: { field: string }) => c.field === "status_category")
      .map((c: { value: unknown }) => c.value);

    for (const value of openValues) {
      expect(value).not.toEqual(["todo", "in_progress"]);
    }
    expect(openValues).toContainEqual(["backlog", "todo", "in_progress"]);
  });

  it("shows a started task that carries no due date", async () => {
    // The table below groups this as "Today" off its start date alone; the
    // section agrees rather than needing a deadline before it will look.
    mockMyTasks({
      rules: buildTaskListResponse([
        buildTask({
          id: 1,
          title: "Draft the launch post",
          start_date: "2026-08-10T09:00:00Z",
          due_date: null,
        }),
        buildTask({ id: 2, title: "Sign the contract", due_date: "2026-08-11T09:00:00Z" }),
      ]),
    });

    renderFocus();

    expect(await screen.findByText("Draft the launch post")).toBeInTheDocument();
    // Dated work still leads: a deadline outranks work that merely started.
    const titles = screen
      .getAllByRole("link")
      .map((link) => link.textContent)
      .filter((title) => title === "Draft the launch post" || title === "Sign the contract");
    expect(titles).toEqual(["Sign the contract", "Draft the launch post"]);
  });

  it("never nests condition groups deeper than the API accepts", async () => {
    mockMyTasks({});
    renderFocus();

    await waitFor(() => expect(captured.length).toBeGreaterThan(0));
    const conditions = JSON.parse(captured[0].get("conditions") ?? "[]");

    // How many groups deep the payload goes; leaves do not count. The API's
    // _MAX_GROUP_DEPTH of 3 permits two group levels and rejects the whole
    // query with a 400 at three.
    const groupDepth = (nodes: unknown[]): number =>
      Math.max(
        0,
        ...nodes.map((node) => {
          const group = node as { conditions?: unknown[] };
          return group.conditions ? 1 + groupDepth(group.conditions) : 0;
        })
      );

    expect(groupDepth(conditions)).toBeLessThanOrEqual(2);
  });

  it("drops the priority leg when the user turns urgent work off", async () => {
    mockMyTasks({});
    renderFocus({ includeHighPriority: false });

    await waitFor(() => expect(captured.length).toBeGreaterThan(0));
    const conditions = JSON.parse(captured[0].get("conditions") ?? "[]");

    const fields = conditions[0].conditions.flatMap((leg: { conditions: { field: string }[] }) =>
      leg.conditions.map((c) => c.field)
    );
    expect(fields).not.toContain("priority");
  });

  it("shows every task that matches, with no cutoff", async () => {
    // A task either meets the rules and belongs here, or it does not. There is
    // no display cap: a shorter list comes from a tighter date window.
    mockMyTasks({
      rules: buildTaskListResponse(
        Array.from({ length: 12 }, (_, index) =>
          buildTask({
            id: index + 1,
            title: `Task ${index + 1}`,
            due_date: `2026-08-${10 + index}T09:00:00Z`,
          })
        )
      ),
    });

    renderFocus();

    expect(await screen.findByText("Task 1")).toBeInTheDocument();
    expect(screen.getByText("Task 12")).toBeInTheDocument();
    expect(screen.getByText("0 of 12 done")).toBeInTheDocument();
  });

  it("holds the day's total steady as work gets completed", async () => {
    // Completing something re-labels a task already on the list; it must never
    // pull another one in and grow the denominator underneath the user.
    const done = {
      id: 9,
      project_id: 1,
      name: "Done",
      category: "done" as const,
      position: 3,
      is_default: false,
    };
    mockMyTasks({
      rules: buildTaskListResponse([
        buildTask({ id: 1, title: "One", due_date: "2026-08-10T09:00:00Z" }),
        buildTask({ id: 2, title: "Two", due_date: "2026-08-11T09:00:00Z" }),
        buildTask({
          id: 3,
          title: "Three",
          due_date: "2026-08-12T09:00:00Z",
          completed_at: new Date().toISOString(),
          task_status: done,
        }),
      ]),
    });

    renderFocus();

    expect(await screen.findByText("1 of 3 done")).toBeInTheDocument();
    expect(screen.getByText("One")).toBeInTheDocument();
    expect(screen.getByText("Two")).toBeInTheDocument();
    expect(screen.getByText("Three")).toBeInTheDocument();
  });

  it("says so when the rules match more than one page", async () => {
    mockMyTasks({
      rules: {
        ...buildTaskListResponse([buildTask({ id: 1, title: "One" })]),
        total_count: 140,
      },
    });

    renderFocus();

    expect(
      await screen.findByText("Showing the first 1. Narrow the date window for a shorter list.")
    ).toBeInTheDocument();
  });

  it("keeps a pinned task even when it does not match the rules", async () => {
    mockMyTasks({
      rules: buildTaskListResponse([]),
      pins: buildTaskListResponse([
        buildTask({ id: 42, guild_id: 1, title: "Pinned far-future task" }),
      ]),
    });

    renderFocus({ pins: [{ guild_id: 1, task_id: 42 }] });

    expect(await screen.findByText("Pinned far-future task")).toBeInTheDocument();
  });

  it("does not mistake a same-numbered task in another guild for the pinned one", async () => {
    // /me/tasks filters run per guild against a shared id space, so an
    // `id IN (…)` query returns task 7 from every guild the user belongs to.
    mockMyTasks({
      rules: buildTaskListResponse([]),
      pins: buildTaskListResponse([
        buildTask({ id: 7, guild_id: 1, title: "Someone else's task 7" }),
        buildTask({ id: 7, guild_id: 2, title: "The pinned task 7" }),
      ]),
    });

    renderFocus({ pins: [{ guild_id: 2, task_id: 7 }] });

    expect(await screen.findByText("The pinned task 7")).toBeInTheDocument();
    expect(screen.queryByText("Someone else's task 7")).not.toBeInTheDocument();
  });

  it("checks a task off from the list", async () => {
    mockMyTasks({
      rules: buildTaskListResponse([
        buildTask({ id: 1, title: "Fix the deploy script", due_date: "2026-08-10T09:00:00Z" }),
      ]),
    });

    const { changeTaskStatus } = renderFocus();
    const checkbox = await screen.findByLabelText("Mark task as done");
    await userEvent.click(checkbox);

    expect(changeTaskStatus).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }), "done");
  });

  it("reopens a task that was completed today", async () => {
    mockMyTasks({
      rules: buildTaskListResponse([
        buildTask({
          id: 3,
          title: "Ship the migration",
          completed_at: "2026-08-10T08:00:00Z",
          task_status: {
            id: 9,
            project_id: 1,
            name: "Done",
            category: "done",
            position: 3,
            is_default: false,
          },
        }),
      ]),
    });

    const { changeTaskStatus } = renderFocus();
    const checkbox = await screen.findByLabelText("Mark task as in progress");
    await userEvent.click(checkbox);

    expect(changeTaskStatus).toHaveBeenCalledWith(
      expect.objectContaining({ id: 3 }),
      "in_progress"
    );
  });

  it("only asks for completions since the start of today", async () => {
    mockMyTasks({});
    renderFocus();

    await waitFor(() => expect(captured.length).toBeGreaterThan(0));
    const conditions = JSON.parse(captured[0].get("conditions") ?? "[]");
    const doneLeg = conditions[0].conditions.at(-1);
    const since = new Date(
      doneLeg.conditions.find((c: { field: string }) => c.field === "completed_at").value
    );

    const midnight = new Date();
    midnight.setHours(0, 0, 0, 0);
    expect(since.getTime()).toBe(midnight.getTime());
  });

  it("drops a pinned task that was finished on an earlier day", async () => {
    // The pin query carries no date filter, so yesterday's finished work would
    // otherwise sit in "completed today" indefinitely.
    const yesterday = new Date();
    yesterday.setDate(yesterday.getDate() - 1);

    mockMyTasks({
      rules: buildTaskListResponse([]),
      pins: buildTaskListResponse([
        buildTask({
          id: 55,
          guild_id: 1,
          title: "Finished yesterday",
          completed_at: yesterday.toISOString(),
          task_status: {
            id: 9,
            project_id: 1,
            name: "Done",
            category: "done",
            position: 3,
            is_default: false,
          },
        }),
      ]),
    });

    renderFocus({ pins: [{ guild_id: 1, task_id: 55 }] });

    expect(
      await screen.findByText("Nothing needs your attention right now. Pin a task to keep it here.")
    ).toBeInTheDocument();
    expect(screen.queryByText("Finished yesterday")).not.toBeInTheDocument();
  });

  it("keeps a pinned task that was finished today", async () => {
    mockMyTasks({
      rules: buildTaskListResponse([]),
      pins: buildTaskListResponse([
        buildTask({
          id: 56,
          guild_id: 1,
          title: "Finished today",
          completed_at: new Date().toISOString(),
          task_status: {
            id: 9,
            project_id: 1,
            name: "Done",
            category: "done",
            position: 3,
            is_default: false,
          },
        }),
      ]),
    });

    renderFocus({ pins: [{ guild_id: 1, task_id: 56 }] });

    const done = await screen.findByText("Finished today");
    expect(done).toHaveClass("line-through");
    expect(screen.getByText("1 of 1 done")).toBeInTheDocument();
  });

  it("invites the user to pin something when there is nothing to show", async () => {
    mockMyTasks({});
    renderFocus();

    expect(
      await screen.findByText("Nothing needs your attention right now. Pin a task to keep it here.")
    ).toBeInTheDocument();
  });
});
