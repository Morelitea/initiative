/**
 * The board's Fields menu: what a card shows, and that turning something off
 * actually takes it off the card.
 *
 * The cards are memoized on prop identity, so "the menu changed the state" and
 * "the card re-rendered" are genuinely different claims — these assert the
 * second one, by reading the card.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { buildDefaultTaskStatuses, buildTask, buildTaskListResponse } from "@/__tests__/factories";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { ProjectTasksSection } from "@/components/projects/ProjectTasksSection";

const STATUSES = buildDefaultTaskStatuses(1);

const seedTask = () => {
  const task = buildTask({
    id: 51,
    project_id: 1,
    title: "Draw the map",
    priority: "medium",
    task_status_id: STATUSES[0].id,
  });
  server.use(guildHttp.get("/tasks/", () => HttpResponse.json(buildTaskListResponse([task]))));
};

const board = () =>
  renderPage(
    () => (
      <ProjectTasksSection
        projectId={1}
        initiativeId={1}
        taskStatuses={STATUSES}
        canEditTaskDetails
        canWriteProject
        projectIsArchived={false}
        canViewTaskDetails
        taskHref={(taskId) => `/tasks/${taskId}`}
      />
    ),
    { routerSearch: { view: "kanban" } }
  );

const openFieldsMenu = async () => {
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: /fields/i }));
  return user;
};

beforeEach(() => {
  seedTask();
  localStorage.clear();
});

describe("the board's Fields menu", () => {
  it("shows every field on a board nobody has configured", async () => {
    board();

    expect(await screen.findByText("Draw the map")).toBeInTheDocument();
    expect(screen.getByText(/priority: medium/i)).toBeInTheDocument();
  });

  it("takes a field off the card when it is unchecked", async () => {
    board();
    expect(await screen.findByText(/priority: medium/i)).toBeInTheDocument();

    const user = await openFieldsMenu();
    await user.click(await screen.findByRole("menuitemcheckbox", { name: "Priority" }));

    await waitFor(() => expect(screen.queryByText(/priority: medium/i)).not.toBeInTheDocument());
    // The card itself stays — this hides a field, not the task.
    expect(screen.getByText("Draw the map")).toBeInTheDocument();
  });

  it("never offers to hide the title", async () => {
    board();
    await openFieldsMenu();

    const menu = await screen.findByRole("menu");
    expect(within(menu).queryByRole("menuitemcheckbox", { name: /^title$/i })).toBeNull();
  });

  it("remembers the choice for next time", async () => {
    board();
    const user = await openFieldsMenu();
    await user.click(await screen.findByRole("menuitemcheckbox", { name: "Priority" }));

    await waitFor(() =>
      expect(
        JSON.parse(localStorage.getItem("initiative-project-1-kanban-fields") ?? "{}")
      ).toMatchObject({ priority: false })
    );
  });

  it("offers to put everything back once something is hidden", async () => {
    board();
    const user = await openFieldsMenu();
    await user.click(await screen.findByRole("menuitemcheckbox", { name: "Priority" }));

    await user.click(await screen.findByRole("menuitem", { name: /show all fields/i }));

    await waitFor(() => expect(screen.getByText(/priority: medium/i)).toBeInTheDocument());
  });
});
