/**
 * The task editor's action row: what it offers, and where deleting leaves you.
 *
 * Deleting from a task's page used to drop you at the initiative's projects
 * list — one step further out than you asked to go, and away from the sibling
 * tasks you were most likely working through. It now returns to the project
 * the task belonged to.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import {
  buildInitiative,
  buildPage,
  buildProject,
  buildPropertySummary,
  buildTask,
} from "@/__tests__/factories";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import {
  type ProjectRead,
  type PropertySummary,
  PropertyType,
} from "@/api/generated/initiativeAPI.schemas";

import { TaskEditPage } from "./TaskEditPage";

const GUILD_ID = 1;
const INITIATIVE_ID = 5;
const PROJECT_ID = 7;
const TASK_ID = 2726;

const TASK_ROUTE = "/c/$guildId/i/$initiativeId/projects/$projectId/tasks/$taskId";

/** What the page asked the project list for, newest last. */
const listed: URLSearchParams[] = [];

/** The project the task actually belongs to, which a move can change. */
const renderTaskPage = ({
  taskProjectId = PROJECT_ID,
  /** What the project reports; a column the task uses can be missing from it. */
  statuses,
  recurrence = null,
  lastOccurrence = false,
  properties = [],
  destinations = [],
  keepContentIn = false,
}: {
  taskProjectId?: number;
  /** Other projects the person may move the task into. */
  destinations?: ProjectRead[];
  keepContentIn?: boolean;
  properties?: PropertySummary[];
  statuses?: unknown[];
  recurrence?: string | null;
  /** Deleting just this task trashes it, as nothing comes after it. */
  lastOccurrence?: boolean;
} = {}) => {
  let gone = false;
  const task = {
    ...buildTask({
      id: TASK_ID,
      project_id: taskProjectId,
      title: "Wire the doorbell",
      recurrence,
      properties,
    }),
    series_size: 3,
  };
  const project = buildProject({
    id: taskProjectId,
    initiative_id: INITIATIVE_ID,
    name: "Rewiring",
  });
  const deleted = vi.fn();

  server.use(
    guildHttp.get("/tasks/:taskId", () =>
      gone ? new HttpResponse(null, { status: 404 }) : HttpResponse.json(task)
    ),
    // The collection routes go first: `:projectId` would otherwise swallow
    // them and answer a list request with a single project.
    guildHttp.get("/projects/", ({ request }) => {
      const params = new URL(request.url).searchParams;
      listed.push(params);
      // The move dialog's destinations come a page at a time.
      return HttpResponse.json(
        params.get("writable") === "true" ? buildPage([project, ...destinations]) : [project]
      );
    }),
    guildHttp.get("/projects/writable", () => HttpResponse.json([project])),
    guildHttp.get("/initiatives/:id", () =>
      HttpResponse.json(buildInitiative({ id: INITIATIVE_ID, keep_content_in: keepContentIn }))
    ),
    guildHttp.get("/projects/:projectId", () => HttpResponse.json(project)),
    ...(statuses
      ? [guildHttp.get("/projects/:id/task-statuses/", () => HttpResponse.json(statuses))]
      : []),
    guildHttp.delete("/tasks/:taskId", ({ request }) => {
      const scope = new URL(request.url).searchParams.get("scope");
      gone = scope !== "this" || lastOccurrence;
      deleted(scope);
      return new HttpResponse(null, { status: 204 });
    })
  );

  const { router } = renderPage(TaskEditPage, {
    initialRoute: TASK_ROUTE,
    routeParams: {
      guildId: String(GUILD_ID),
      initiativeId: String(INITIATIVE_ID),
      projectId: String(PROJECT_ID),
      taskId: String(TASK_ID),
    },
  });

  return { router, deleted, task };
};

describe("TaskEditPage", () => {
  const openActionsMenu = async () =>
    userEvent.click(await screen.findByRole("button", { name: /more actions/i }));

  const deleteTheTask = async () => {
    await openActionsMenu();
    await userEvent.click(await screen.findByRole("menuitem", { name: /delete task/i }));
    // The confirm dialog repeats the label; the last match is its button.
    const confirms = await screen.findAllByRole("button", { name: /delete/i });
    await userEvent.click(confirms[confirms.length - 1]);
  };

  it("keeps only save and cancel in the row, with the rest behind one menu", async () => {
    renderTaskPage();

    // Save and cancel are the row; the other four actions used to sit beside
    // them as buttons and now only exist inside the overflow menu.
    expect(await screen.findByRole("button", { name: /save task/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /cancel/i })).toBeInTheDocument();
    for (const name of [/move to project/i, /duplicate task/i, /archive/i, /delete task/i]) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }

    await openActionsMenu();

    for (const name of [/move to project/i, /duplicate task/i, /archive/i, /delete task/i]) {
      expect(await screen.findByRole("menuitem", { name })).toBeInTheDocument();
    }
  });

  it("saves the task and its changed property values in one request", async () => {
    const { task } = renderTaskPage({
      properties: [
        buildPropertySummary({
          property_id: 4,
          name: "Hours",
          type: PropertyType.number,
          value: 1,
        }),
      ],
    });
    const sent: Record<string, unknown>[] = [];
    const put = vi.fn(() => HttpResponse.json([]));
    server.use(
      guildHttp.patch("/tasks/:taskId", async ({ request }) => {
        sent.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json(task);
      }),
      guildHttp.put("/properties/:target/:entityId", put)
    );

    const hours = await screen.findByPlaceholderText("0");
    await userEvent.clear(hours);
    await userEvent.type(hours, "8");
    await userEvent.click(screen.getByRole("button", { name: /save task/i }));

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0].properties).toEqual([{ property_id: 4, value: 8 }]);
    expect(put).not.toHaveBeenCalled();
  });

  it("reports duplicate progress on the trigger once the menu closes", async () => {
    renderTaskPage();
    server.use(
      guildHttp.post("/tasks/:taskId/duplicate", async () => {
        await delay("infinite");
        return new HttpResponse(null, { status: 204 });
      })
    );

    await openActionsMenu();
    await userEvent.click(await screen.findByRole("menuitem", { name: /duplicate task/i }));

    // Selecting the item dismisses the menu holding the "Duplicating…" label,
    // and duplicate opens no dialog — so the trigger has to carry the state.
    const trigger = await screen.findByRole("button", { name: /more actions/i });
    await waitFor(() => expect(trigger).toHaveAttribute("aria-busy", "true"));
  });

  it("still names a status the project has since dropped", async () => {
    // The heading badge used to fall back to the task's own status snapshot.
    // With the badge gone, the select is the only place the status is stated,
    // so it has to resolve a column the project no longer lists.
    renderTaskPage({ statuses: [] });

    // Radix echoes the trigger's value into a hidden native select, so the
    // name legitimately appears more than once; the placeholder is the tell.
    expect(await screen.findAllByText("To Do")).not.toHaveLength(0);
    expect(screen.queryByText(/select status/i)).not.toBeInTheDocument();
  });

  it("opens the move dialog from the actions menu, offering live projects", async () => {
    listed.length = 0;
    renderTaskPage();

    await openActionsMenu();
    await userEvent.click(await screen.findByRole("menuitem", { name: /move to project/i }));

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    // A template takes no tasks moved into it, so the destinations leave
    // templates out.
    const destinations = listed.find((params) => params.get("writable") === "true");
    expect(destinations?.get("is_template")).toBe("false");
  });

  it.each([
    [false, "Elsewhere"],
    [true, "Nearby"],
  ])(
    "offers other initiatives' projects only while content may leave (kept in: %s)",
    async (keepContentIn, offered) => {
      renderTaskPage({
        keepContentIn,
        destinations: [
          buildProject({ id: PROJECT_ID + 1, initiative_id: INITIATIVE_ID + 1, name: "Elsewhere" }),
          buildProject({ id: PROJECT_ID + 2, initiative_id: INITIATIVE_ID, name: "Nearby" }),
        ],
      });

      await openActionsMenu();
      await userEvent.click(await screen.findByRole("menuitem", { name: /move to project/i }));

      // The dialog picks the first destination it offers.
      expect(
        await within(await screen.findByRole("dialog")).findByText(offered)
      ).toBeInTheDocument();
    }
  );

  it("returns to the task's project after deleting it", async () => {
    const { router, deleted } = renderTaskPage();

    await deleteTheTask();

    await waitFor(() => expect(deleted).toHaveBeenCalled());
    await waitFor(() =>
      expect(router.state.location.pathname).toBe(
        `/c/${GUILD_ID}/i/${INITIATIVE_ID}/projects/${PROJECT_ID}`
      )
    );
  });

  it("asks which tasks of a repeating series a delete is for", async () => {
    const { router, deleted } = renderTaskPage({ recurrence: "RRULE:FREQ=DAILY" });

    await openActionsMenu();
    await userEvent.click(await screen.findByRole("menuitem", { name: /delete task/i }));
    expect(await screen.findByLabelText(/all tasks in the series \(3\)/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^delete$/i }));

    // Just this one skips it, so the series and the page stay.
    await waitFor(() => expect(deleted).toHaveBeenCalledWith("this"));
    expect(router.state.location.pathname).toContain(`/tasks/${TASK_ID}`);
  });

  it("leaves the page when just this task was the series' last", async () => {
    const { router, deleted } = renderTaskPage({
      recurrence: "RRULE:FREQ=DAILY;COUNT=2",
      lastOccurrence: true,
    });

    await openActionsMenu();
    await userEvent.click(await screen.findByRole("menuitem", { name: /delete task/i }));
    await userEvent.click(await screen.findByRole("button", { name: /^delete$/i }));

    await waitFor(() => expect(deleted).toHaveBeenCalledWith("this"));
    await waitFor(() =>
      expect(router.state.location.pathname).toBe(
        `/c/${GUILD_ID}/i/${INITIATIVE_ID}/projects/${PROJECT_ID}`
      )
    );
  });

  it("follows the task's own project, not the one left in the path", async () => {
    // Moving the open task rewrites its project without touching the URL, so
    // the path still names the project it came from.
    const MOVED_TO = PROJECT_ID + 1;
    const { router, deleted } = renderTaskPage({ taskProjectId: MOVED_TO });

    await deleteTheTask();

    await waitFor(() => expect(deleted).toHaveBeenCalled());
    await waitFor(() =>
      expect(router.state.location.pathname).toBe(
        `/c/${GUILD_ID}/i/${INITIATIVE_ID}/projects/${MOVED_TO}`
      )
    );
  });
});
