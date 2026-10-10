/**
 * What a board's card shows: the card its view lays out, or the shipped one.
 *
 * The cards are memoized on prop identity, so these read the card rather than
 * the state behind it.
 */
import { screen, waitFor } from "@testing-library/react";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import {
  buildDefaultTaskStatuses,
  buildPropertyDefinition,
  buildPropertySummary,
  buildTask,
  buildTaskListResponse,
  buildToolLayoutSet,
  buildUserSummary,
} from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { ProjectTasksSection } from "@/components/projects/ProjectTasksSection";
import { resetTimeFormat, setTimeFormat } from "@/lib/timeFormat";

const STATUSES = buildDefaultTaskStatuses(1);

const seedTask = (overrides: Record<string, unknown> = {}) => {
  const task = buildTask({
    id: 51,
    project_id: 1,
    title: "Draw the map",
    priority: "medium",
    task_status_id: STATUSES[0].id,
    ...overrides,
  });
  server.use(communityHttp.get("/tasks/", () => HttpResponse.json(buildTaskListResponse([task]))));
};

const board = () =>
  renderPage(
    () => (
      <ProjectTasksSection
        projectId={1}
        initiativeId={1}
        taskStatuses={STATUSES}
        canEditTaskDetails
        projectIsArchived={false}
        taskHref={(taskId) => `/tasks/${taskId}`}
      />
    ),
    { routerSearch: { layout: "board" } }
  );

beforeEach(() => {
  seedTask();
  localStorage.clear();
  resetTimeFormat();
});

describe("a board's card", () => {
  it("shows every field on a board nobody has laid out", async () => {
    seedTask({ description_excerpt: "Start from the coast…", has_description: true });
    board();

    expect(await screen.findByText("Draw the map")).toBeInTheDocument();
    expect(screen.getByText("Start from the coast…")).toBeInTheDocument();
    expect(screen.getByText(/priority: medium/i)).toBeInTheDocument();
  });

  it("shows a task's properties on a board nobody has laid out", async () => {
    seedTask({
      properties: [buildPropertySummary({ property_id: 12, name: "Effort", value: "large" })],
    });
    server.use(
      communityHttp.get("/property-definitions/", () =>
        HttpResponse.json([buildPropertyDefinition({ id: 12, name: "Effort" })])
      )
    );
    board();

    expect(await screen.findByText("large")).toBeInTheDocument();
  });

  it("shows the shipped card for a board laid out with none", async () => {
    server.use(
      communityHttp.get("/layouts/", () =>
        HttpResponse.json(
          buildToolLayoutSet({
            layouts: [
              {
                kind: "board",
                is_default: true,
                // As the server sends a board changed to hold no card.
                definition: { card: null, columns: null },
                updated_at: "2026-10-01T12:00:00.000Z",
              },
            ],
          })
        )
      )
    );
    board();

    expect(await screen.findByText(/priority: medium/i)).toBeInTheDocument();
  });

  it("shows only what the board's card names", async () => {
    seedTask({ description_excerpt: "Start from the coast…", has_description: true });
    server.use(
      communityHttp.get("/layouts/", () =>
        HttpResponse.json(
          buildToolLayoutSet({
            layouts: [
              {
                kind: "board",
                is_default: true,
                definition: {
                  card: {
                    type: "card",
                    children: [{ type: "field", props: { field: "title" } }],
                  },
                },
                updated_at: "2026-10-01T12:00:00.000Z",
              },
            ],
          })
        )
      )
    );
    board();

    expect(await screen.findByText("Draw the map")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText(/priority: medium/i)).not.toBeInTheDocument());
    expect(screen.queryByText("Start from the coast…")).not.toBeInTheDocument();
  });
});

describe("a card's dates", () => {
  it("reads on the clock the account picked", async () => {
    // These lines used to call `toLocaleString()` directly, which ignores the
    // preference — a reader on 24-hour still got AM/PM on every card.
    seedTask({ due_date: "2026-08-03T21:15:00Z" });
    setTimeFormat("24");
    board();

    const due = await screen.findByText(/^Due:/);
    expect(due.textContent).not.toMatch(/\b(AM|PM)\b/);
  });

  it("still says AM/PM for a reader who picked 12-hour", async () => {
    seedTask({ due_date: "2026-08-03T21:15:00Z" });
    setTimeFormat("12");
    board();

    const due = await screen.findByText(/^Due:/);
    expect(due.textContent).toMatch(/\b(AM|PM)\b/);
  });
});

describe("a card's excerpt", () => {
  it("names the people it mentions as they are called now", async () => {
    seedTask({ description_excerpt: "Start from the coast with @[](12)", has_description: true });
    server.use(
      communityHttp.get("/users/search", () =>
        HttpResponse.json({
          items: [buildUserSummary({ id: 12, display_name: "Ada King" })],
          total: 1,
          page: 1,
          page_size: 100,
        })
      )
    );
    board();

    expect(await screen.findByText("@Ada King")).toBeInTheDocument();
    expect(screen.getByText(/Start from the coast with/)).toBeInTheDocument();
  });
});
