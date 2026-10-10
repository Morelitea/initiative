/**
 * The view editor, worked as a manager works it: change the open view in the
 * outline or on the canvas, see it at once, and nothing is stored until Save.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  buildDefaultTaskStatuses,
  buildPropertyDefinition,
  buildTask,
  buildTaskListResponse,
  buildToolViewSet,
} from "@/__tests__/factories";
import { buildSavedViewSet } from "@/__tests__/factories/toolView.factory";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { ToolViewSetWrite } from "@/api/generated/initiativeAPI.schemas";

import { ViewEditor } from "./ViewEditor";

const STATUSES = buildDefaultTaskStatuses(1);

let saves: ToolViewSetWrite[] = [];

const editor = (slug: string, onClose = vi.fn()) => {
  renderPage(() => (
    <ViewEditor
      projectId={1}
      initiativeId={1}
      statuses={STATUSES}
      set={buildToolViewSet()}
      initialSlug={slug}
      onClose={onClose}
    />
  ));
  return { user: userEvent.setup(), onClose };
};

const outline = () => screen.findByRole("navigation", { name: /outline/i });
const canvas = () => screen.findByRole("region", { name: /preview/i });

beforeEach(() => {
  saves = [];
  server.use(
    communityHttp.get("/tasks/", () =>
      HttpResponse.json(
        buildTaskListResponse([
          buildTask({
            id: 7,
            project_id: 1,
            title: "Draw the map",
            priority: "medium",
            task_status_id: STATUSES[0].id,
          }),
        ])
      )
    ),
    communityHttp.get("/property-definitions/", () =>
      HttpResponse.json([buildPropertyDefinition({ id: 12, name: "Effort" })])
    ),
    communityHttp.put("/views/", async ({ request }) => {
      const body = (await request.json()) as ToolViewSetWrite;
      saves.push(body);
      return HttpResponse.json(buildSavedViewSet(body));
    })
  );
});

describe("ViewEditor", () => {
  it("takes a field off the card at once, and stores it only on Save", async () => {
    const { user } = editor("board");
    expect(await within(await canvas()).findByText(/priority: medium/i)).toBeInTheDocument();

    await user.click(within(await outline()).getByRole("button", { name: /hide priority/i }));

    expect(within(await canvas()).queryByText(/priority: medium/i)).not.toBeInTheDocument();
    expect(saves).toEqual([]);
    await user.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(saves).toHaveLength(1));
    const board = saves[0].views.find((view) => view.slug === "board");
    expect(JSON.stringify(board?.definition.card)).not.toContain('"priority"');
  });

  it("puts back what was undone", async () => {
    const { user } = editor("board");
    await within(await canvas()).findByText(/priority: medium/i);

    await user.click(within(await outline()).getByRole("button", { name: /hide priority/i }));
    await user.click(screen.getByRole("button", { name: /^undo$/i }));

    expect(within(await canvas()).getByText(/priority: medium/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^save$/i })).toBeDisabled();
  });

  it("selects the part clicked on the canvas, in the outline", async () => {
    const { user } = editor("board");

    await user.click(await within(await canvas()).findByText(/priority: medium/i));

    expect(within(await outline()).getByRole("button", { name: "Priority" })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
  });

  it("adds a property to a table as a column, named by its id", async () => {
    const { user } = editor("table");

    await user.click(await within(await outline()).findByRole("button", { name: /^add$/i }));
    await user.click(await screen.findByRole("button", { name: "Effort" }));
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(saves).toHaveLength(1));
    expect(saves[0].views.find((view) => view.slug === "table")?.definition.columns).toEqual([
      "title",
      "startDate",
      "dueDate",
      "priority",
      "tags",
      "comments",
      "property:12",
    ]);
  });

  it("asks before leaving with changes, and leaves at once without", async () => {
    const { user, onClose } = editor("board");
    await within(await canvas()).findByText(/priority: medium/i);

    await user.click(within(await outline()).getByRole("button", { name: /hide priority/i }));
    await user.click(screen.getByRole("button", { name: /close the editor/i }));
    expect(await screen.findByText(/leave without saving/i)).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: /^leave$/i }));

    expect(onClose).toHaveBeenCalled();
  });
});
