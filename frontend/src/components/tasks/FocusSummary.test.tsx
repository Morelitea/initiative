import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  buildTask,
  buildTaskAssignee,
  buildTaskListResponse,
  buildUser,
  resetFactories,
} from "@/__tests__/factories";
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
const VIEWER_ID = 4242;

/** The viewer, still holding their part. */
const mine = (overrides = {}) => buildTaskAssignee({ id: VIEWER_ID, ...overrides });
/** The viewer, finished. */
const mineFinished = (at = new Date().toISOString()) => mine({ completed_at: at });

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

  const setMyPartCompleted = vi.fn().mockResolvedValue(undefined);
  const Harness = () => {
    const focus = useFocusSummary();
    return (
      <FocusSummary
        focus={focus}
        activeGuildId={1}
        setMyPartCompleted={setMyPartCompleted}
        isUpdating={false}
      />
    );
  };

  return {
    ...renderPage(Harness, {
      queryClient,
      auth: { user: buildUser({ id: VIEWER_ID }) },
    }),
    setMyPartCompleted,
  };
}

beforeEach(() => {
  resetFactories();
  captured.length = 0;
});

describe("FocusSummary", () => {
  it("lists work still mine and keeps what I finished today visible", async () => {
    mockMyTasks({
      rules: buildTaskListResponse([
        buildTask({
          id: 1,
          title: "Fix the deploy script",
          due_date: "2026-08-10T09:00:00Z",
          assignees: [mine()],
        }),
        buildTask({
          id: 2,
          title: "Review the release notes",
          due_date: "2026-08-11T09:00:00Z",
          assignees: [mine()],
        }),
        buildTask({ id: 3, title: "Ship the migration", assignees: [mineFinished()] }),
      ]),
    });

    renderFocus();

    expect(await screen.findByText("Fix the deploy script")).toBeInTheDocument();
    expect(screen.getByText("Review the release notes")).toBeInTheDocument();

    const finished = screen.getByText("Ship the migration");
    expect(finished).toHaveClass("line-through");
    expect(screen.getByText("1 of 3 done")).toBeInTheDocument();
  });

  it("counts a task as finished on my completion, not the task's status", async () => {
    // Handed to review: the task is wide open, but my share of it is over, so
    // it belongs in the day's wins rather than the list of things to do.
    mockMyTasks({
      rules: buildTaskListResponse([
        buildTask({
          id: 1,
          title: "Handed to review",
          assignees: [mineFinished(), buildTaskAssignee()],
          task_status: {
            id: 2,
            project_id: 1,
            name: "In Review",
            category: "in_progress",
            position: 1,
            is_default: false,
          },
        }),
      ]),
    });

    renderFocus();

    expect(await screen.findByText("Handed to review")).toHaveClass("line-through");
    expect(screen.getByText("1 of 1 done")).toBeInTheDocument();
  });

  it("ignores a co-assignee's completion", async () => {
    mockMyTasks({
      rules: buildTaskListResponse([
        buildTask({
          id: 1,
          title: "Shared work",
          due_date: "2026-08-10T09:00:00Z",
          assignees: [mine(), buildTaskAssignee({ completed_at: new Date().toISOString() })],
        }),
      ]),
    });

    renderFocus();

    expect(await screen.findByText("Shared work")).not.toHaveClass("line-through");
    expect(screen.getByText("0 of 1 done")).toBeInTheDocument();
  });

  it("asks for work still mine that is due soon or urgent, plus today's wins", async () => {
    mockMyTasks({});
    renderFocus({ dueWithinDays: 2, includeHighPriority: true });

    await waitFor(() => expect(captured.length).toBeGreaterThan(0));
    const conditions = JSON.parse(captured[0].get("conditions") ?? "[]");

    expect(conditions).toHaveLength(1);
    expect(conditions[0].logic).toBe("or");

    const stillMine = { field: "my_completion", op: "is_null", value: true };
    const [dueLeg, urgentLeg, doneLeg] = conditions[0].conditions;

    // Due-soon OR urgent, as sibling AND legs: an AND between date and priority
    // would empty the list on exactly the days it matters most, and a third
    // level of nesting is rejected outright by the API's group-depth cap.
    expect(dueLeg.conditions).toEqual([
      stillMine,
      { field: "due_date", op: "lte", value: expect.any(String) },
    ]);
    expect(urgentLeg.conditions).toEqual([
      stillMine,
      { field: "priority", op: "in_", value: ["urgent", "high"] },
    ]);
    expect(doneLeg).toEqual({
      field: "my_completion",
      op: "gte",
      value: expect.any(String),
    });

    const raw = captured[0].get("conditions") ?? "";
    // No status filter: closing a task already finishes every assignee's part,
    // so the task's status has nothing left to say here.
    expect(raw).not.toContain("status_category");
    // The list spans every guild and answers only to its own settings.
    expect(raw).not.toContain("guild_id");
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

    expect(captured[0].get("conditions") ?? "").not.toContain("priority");
  });

  it("shows every task that matches, with no cutoff", async () => {
    mockMyTasks({
      rules: buildTaskListResponse(
        Array.from({ length: 12 }, (_, index) =>
          buildTask({
            id: index + 1,
            title: `Task ${index + 1}`,
            due_date: `2026-08-${10 + index}T09:00:00Z`,
            assignees: [mine()],
          })
        )
      ),
    });

    renderFocus();

    expect(await screen.findByText("Task 1")).toBeInTheDocument();
    expect(screen.getByText("Task 12")).toBeInTheDocument();
    expect(screen.getByText("0 of 12 done")).toBeInTheDocument();
  });

  it("says so when the rules match more than one page", async () => {
    mockMyTasks({
      rules: {
        ...buildTaskListResponse([buildTask({ id: 1, title: "One", assignees: [mine()] })]),
        total_count: 140,
      },
    });

    renderFocus();

    expect(
      await screen.findByText("Showing the first 1. Narrow the date window for a shorter list.")
    ).toBeInTheDocument();
  });

  // --- pins -----------------------------------------------------------------

  it("keeps a pinned task even when it does not match the rules", async () => {
    mockMyTasks({
      rules: buildTaskListResponse([]),
      pins: buildTaskListResponse([
        buildTask({ id: 42, guild_id: 1, title: "Pinned far-future task", assignees: [mine()] }),
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
        buildTask({ id: 7, guild_id: 1, title: "Someone else's task 7", assignees: [mine()] }),
        buildTask({ id: 7, guild_id: 2, title: "The pinned task 7", assignees: [mine()] }),
      ]),
    });

    renderFocus({ pins: [{ guild_id: 2, task_id: 7 }] });

    expect(await screen.findByText("The pinned task 7")).toBeInTheDocument();
    expect(screen.queryByText("Someone else's task 7")).not.toBeInTheDocument();
  });

  // --- the daily reset ------------------------------------------------------

  it("only asks for completions since the start of today", async () => {
    mockMyTasks({});
    renderFocus();

    await waitFor(() => expect(captured.length).toBeGreaterThan(0));
    const conditions = JSON.parse(captured[0].get("conditions") ?? "[]");
    const since = new Date(conditions[0].conditions.at(-1).value);

    const midnight = new Date();
    midnight.setHours(0, 0, 0, 0);
    expect(since.getTime()).toBe(midnight.getTime());
  });

  it("drops a pinned task I finished on an earlier day", async () => {
    // The pin query carries no date filter, so yesterday's finished work would
    // otherwise sit in "done today" indefinitely.
    const yesterday = new Date();
    yesterday.setDate(yesterday.getDate() - 1);

    mockMyTasks({
      rules: buildTaskListResponse([]),
      pins: buildTaskListResponse([
        buildTask({
          id: 55,
          guild_id: 1,
          title: "Finished yesterday",
          assignees: [mineFinished(yesterday.toISOString())],
        }),
      ]),
    });

    renderFocus({ pins: [{ guild_id: 1, task_id: 55 }] });

    expect(
      await screen.findByText("Nothing needs your attention right now. Pin a task to keep it here.")
    ).toBeInTheDocument();
    expect(screen.queryByText("Finished yesterday")).not.toBeInTheDocument();
  });

  it("keeps a pinned task I finished today", async () => {
    mockMyTasks({
      rules: buildTaskListResponse([]),
      pins: buildTaskListResponse([
        buildTask({
          id: 56,
          guild_id: 1,
          title: "Finished today",
          assignees: [mineFinished()],
        }),
      ]),
    });

    renderFocus({ pins: [{ guild_id: 1, task_id: 56 }] });

    expect(await screen.findByText("Finished today")).toHaveClass("line-through");
    expect(screen.getByText("1 of 1 done")).toBeInTheDocument();
  });

  // --- checking off ---------------------------------------------------------

  it("marks my part done, and says so when the task is shared", async () => {
    mockMyTasks({
      rules: buildTaskListResponse([
        buildTask({
          id: 1,
          title: "Shared work",
          due_date: "2026-08-10T09:00:00Z",
          assignees: [mine(), buildTaskAssignee()],
        }),
      ]),
    });

    const { setMyPartCompleted } = renderFocus();
    await userEvent.click(await screen.findByLabelText("Done with my part"));

    expect(setMyPartCompleted).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }), true);
  });

  it("offers to finish the task outright when nobody else is on it", async () => {
    // Sole assignee: your part is the whole task, and the server closes it.
    mockMyTasks({
      rules: buildTaskListResponse([
        buildTask({
          id: 1,
          title: "Solo work",
          due_date: "2026-08-10T09:00:00Z",
          assignees: [mine()],
        }),
      ]),
    });

    const { setMyPartCompleted } = renderFocus();
    await userEvent.click(await screen.findByLabelText("Mark done"));

    expect(setMyPartCompleted).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }), true);
  });

  it("takes back a completion", async () => {
    mockMyTasks({
      rules: buildTaskListResponse([
        buildTask({ id: 3, title: "Ship the migration", assignees: [mineFinished()] }),
      ]),
    });

    const { setMyPartCompleted } = renderFocus();
    await userEvent.click(await screen.findByLabelText("Not done after all"));

    expect(setMyPartCompleted).toHaveBeenCalledWith(expect.objectContaining({ id: 3 }), false);
  });

  it("invites the user to pin something when there is nothing to show", async () => {
    mockMyTasks({});
    renderFocus();

    expect(
      await screen.findByText("Nothing needs your attention right now. Pin a task to keep it here.")
    ).toBeInTheDocument();
  });
});
