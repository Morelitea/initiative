/**
 * Where deleting a task leaves you.
 *
 * Deleting from a task's page used to drop you at the initiative's projects
 * list — one step further out than you asked to go, and away from the sibling
 * tasks you were most likely working through. It now returns to the project
 * the task belonged to.
 */
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { buildProject, buildTask } from "@/__tests__/factories";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";

import { TaskEditPage } from "./TaskEditPage";

const GUILD_ID = 1;
const INITIATIVE_ID = 5;
const PROJECT_ID = 7;
const TASK_ID = 2726;

const TASK_ROUTE = "/g/$guildId/i/$initiativeId/projects/$projectId/tasks/$taskId";

/** The project the task actually belongs to, which a move can change. */
const renderTaskPage = ({ taskProjectId = PROJECT_ID }: { taskProjectId?: number } = {}) => {
  const task = buildTask({ id: TASK_ID, project_id: taskProjectId, title: "Wire the doorbell" });
  const project = buildProject({
    id: taskProjectId,
    initiative_id: INITIATIVE_ID,
    name: "Rewiring",
  });
  const deleted = vi.fn();

  server.use(
    guildHttp.get("/tasks/:taskId", () => HttpResponse.json(task)),
    // The collection routes go first: `:projectId` would otherwise swallow
    // them and answer a list request with a single project.
    guildHttp.get("/projects/", () => HttpResponse.json([project])),
    guildHttp.get("/projects/writable", () => HttpResponse.json([project])),
    guildHttp.get("/projects/:projectId", () => HttpResponse.json(project)),
    guildHttp.delete("/tasks/:taskId", () => {
      deleted();
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

  return { router, deleted };
};

describe("TaskEditPage", () => {
  const deleteTheTask = async () => {
    fireEvent.click(await screen.findByRole("button", { name: /delete task/i }));
    // The confirm dialog repeats the label; the last match is its button.
    const confirms = await screen.findAllByRole("button", { name: /delete/i });
    fireEvent.click(confirms[confirms.length - 1]);
  };

  it("returns to the task's project after deleting it", async () => {
    const { router, deleted } = renderTaskPage();

    await deleteTheTask();

    await waitFor(() => expect(deleted).toHaveBeenCalled());
    await waitFor(() =>
      expect(router.state.location.pathname).toBe(
        `/g/${GUILD_ID}/i/${INITIATIVE_ID}/projects/${PROJECT_ID}`
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
        `/g/${GUILD_ID}/i/${INITIATIVE_ID}/projects/${MOVED_TO}`
      )
    );
  });
});
