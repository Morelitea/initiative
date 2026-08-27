/**
 * What a task view shows, and what a link to it means.
 *
 * The three sources are ranked, not merged: the URL, then this person's
 * remembered filters, then the project's default preset. These cover the
 * ranking end-to-end — including that picking a preset writes it to the URL,
 * so the view is linkable.
 *
 * The preset picker lives in the filter panel, since picking one sets every
 * field below it; opening the panel is the first step of most of these.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  buildDefaultFilterPresets,
  buildDefaultTaskStatuses,
  buildTag,
  buildTaskListResponse,
} from "@/__tests__/factories";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { ProjectTasksSection } from "@/components/projects/ProjectTasksSection";

type Condition = { field?: string; op?: string; value?: unknown; logic?: string };

/** The `conditions` of the most recent tasks request. */
let lastConditions: Condition[] = [];

const captureTaskRequests = () => {
  lastConditions = [];
  server.use(
    guildHttp.get("/tasks/", ({ request }) => {
      const raw = new URL(request.url).searchParams.get("conditions");
      if (raw) lastConditions = JSON.parse(raw) as Condition[];
      return HttpResponse.json(buildTaskListResponse([]));
    })
  );
};

const section = (options: { routerSearch?: Record<string, unknown> } = {}) =>
  renderPage(
    () => (
      <ProjectTasksSection
        projectId={1}
        initiativeId={1}
        taskStatuses={buildDefaultTaskStatuses(1)}
        canEditTaskDetails
        canWriteProject
        projectIsArchived={false}
        canViewTaskDetails
        onTaskClick={vi.fn()}
      />
    ),
    { routerSearch: options.routerSearch ?? {} }
  );

const fieldsUsed = () => lastConditions.map((entry) => entry.field ?? `group:${entry.logic}`);

/** The guild's tags, which the default handler leaves empty. */
const withTags = (ids: number[]) => {
  server.use(
    guildHttp.get("/tags/", () =>
      HttpResponse.json(ids.map((id) => buildTag({ id, name: `Tag ${id}` })))
    )
  );
};

/** Seed this person's remembered filters for project 1. */
const rememberFilters = (spec: Record<string, unknown>) => {
  server.use(
    http.get("/api/v1/user-view-preferences", () =>
      HttpResponse.json({
        items: { "project:1:view-filters": { activePresetSlug: null, ...spec } },
      })
    )
  );
};

/** The picker is inside the filter panel, which starts closed. */
const openFilters = async () => {
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: /filters/i }));
  return user;
};

/** Toggle one of the assignee tokens ("Assigned to me" / "Unassigned").
 *  They live inside the assignee picker, not as checkboxes of their own —
 *  they answer the same question the people list does. */
const toggleAssigneeToken = async (user: ReturnType<typeof userEvent.setup>, name: RegExp) => {
  await user.click(await screen.findByRole("combobox", { name: /filter by assignee/i }));
  await user.click(await screen.findByRole("option", { name }));
  await user.keyboard("{Escape}");
};

/** Pick a preset the way someone would, rather than seeding the URL.
 *
 *  `renderPage` re-seeds its `routerSearch` whenever the page navigates to an
 *  empty search, so a test that starts from `?preset=…` can never observe the
 *  param being dropped. Going through the picker avoids that entirely. */
const pickPreset = async (user: ReturnType<typeof userEvent.setup>, name: string) => {
  await user.click(await screen.findByRole("combobox", { name: /preset/i }));
  await user.click(await screen.findByRole("option", { name }));
};

beforeEach(() => {
  captureTaskRequests();
});

describe("ProjectTasksSection presets", () => {
  it("shows the project's default preset when the URL says nothing", async () => {
    section();
    await openFilters();

    expect(await screen.findByRole("combobox", { name: /preset/i })).toHaveTextContent("All");
  });

  it("offers statuses and status categories in one control", async () => {
    // One question — "which statuses?" — answered either by naming them or by
    // naming a category, so they share a control rather than sitting in two
    // that could contradict each other.
    section();
    const user = await openFilters();

    await user.click(await screen.findByRole("combobox", { name: /filter by status/i }));

    // "To Do" is a status of this project; the categories sit under their own
    // heading below. A project's statuses are often named after categories, so
    // "Backlog" legitimately appears on both sides of the control.
    expect(await screen.findByRole("option", { name: "To Do" })).toBeInTheDocument();
    expect(await screen.findByText(/status category/i)).toBeInTheDocument();
    expect(screen.getAllByRole("option", { name: "Backlog" })).toHaveLength(2);
  });

  it("applies the preset the URL names", async () => {
    section({ routerSearch: { preset: "incomplete" } });

    await waitFor(() => expect(fieldsUsed()).toContain("status_category"));
    const category = lastConditions.find((entry) => entry.field === "status_category");
    expect(category?.value).toEqual(["backlog", "todo", "in_progress"]);
    // Status *ids* are per-project, so a shared preset must never carry them.
    expect(fieldsUsed()).not.toContain("task_status_id");
  });

  it("asks for unassigned tasks with is_null, which no id list can express", async () => {
    section({ routerSearch: { preset: "unassigned" } });

    await waitFor(() =>
      expect(lastConditions).toContainEqual({
        field: "assignee_ids",
        op: "is_null",
        value: true,
      })
    );
  });

  it("keeps 'me' a token, so the same link works for whoever opens it", async () => {
    section({ routerSearch: { preset: "mine" } });

    await waitFor(() =>
      expect(lastConditions).toContainEqual({
        field: "assignee_ids",
        op: "in_",
        value: ["me"],
      })
    );
  });

  it("offers 'me' and 'unassigned' inside the assignee picker", async () => {
    // Neither is a person the roster could return — the server resolves both
    // per request, which is what keeps a shared preset portable. They answer
    // the same question as the people list, so they live in the same control.
    section();
    const user = await openFilters();
    await pickPreset(user, "Mine");

    await user.click(await screen.findByRole("combobox", { name: /filter by assignee/i }));

    await user.click(await screen.findByRole("option", { name: /^Unassigned$/ }));

    await waitFor(() =>
      expect(lastConditions).toContainEqual({
        logic: "or",
        conditions: [
          { field: "assignee_ids", op: "is_null", value: true },
          { field: "assignee_ids", op: "in_", value: ["me"] },
        ],
      })
    );
  });

  it("names the chosen token on the assignee trigger", async () => {
    // A trigger still reading "All assignees" while "me" is on would
    // misdescribe the list.
    section();
    const user = await openFilters();
    await pickPreset(user, "Mine");

    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: /filter by assignee/i })).toHaveTextContent(
        "Assigned to me"
      )
    );
  });

  it("lets go of 'me' from the same picker", async () => {
    section();
    const user = await openFilters();
    await pickPreset(user, "Mine");

    await toggleAssigneeToken(user, /^Assigned to me$/);

    await waitFor(() => expect(fieldsUsed()).not.toContain("assignee_ids"));
  });

  it("does not throw the reader back to the top of the list when picking one", async () => {
    // Naming the preset in the URL is bookkeeping about the list you are
    // already looking at, so the router's scroll reset must not fire.
    const { router } = section();
    const user = await openFilters();
    const navigate = vi.spyOn(router, "navigate");

    await pickPreset(user, "Mine");

    await waitFor(() => expect(navigate).toHaveBeenCalled());
    expect(navigate.mock.calls.at(-1)?.[0]).toMatchObject({
      replace: true,
      resetScroll: false,
    });
  });

  it("names the chosen preset in the URL, so the view can be linked", async () => {
    const { router } = section();
    const user = await openFilters();

    await user.click(await screen.findByRole("combobox", { name: /preset/i }));
    await user.click(await screen.findByRole("option", { name: "Mine" }));

    await waitFor(() =>
      expect((router.state.location.search as { preset?: string }).preset).toBe("mine")
    );
  });

  it("honours the view mode named in the URL", async () => {
    section({ routerSearch: { view: "kanban" } });

    await waitFor(() =>
      expect(screen.getByRole("tab", { name: /kanban/i })).toHaveAttribute("data-state", "active")
    );
  });

  it("keeps a remembered tag that still exists", async () => {
    // The positive control for the next case: this proves the remembered
    // filter reaches the query at all.
    withTags([7]);
    rememberFilters({ tag_ids: [7] });
    section();

    await waitFor(() =>
      expect(lastConditions).toContainEqual({ field: "tag_ids", op: "in_", value: [7] })
    );
  });

  it("drops a remembered tag that no longer exists rather than emptying the list", async () => {
    // A deleted tag does not quietly stop narrowing: sent as `tag_ids in (999)`
    // it matches nothing, so the list goes empty and the control that would
    // explain why has no option left to render.
    withTags([7]);
    rememberFilters({ tag_ids: [999] });
    section();

    // Both in one tick: the first request goes out before the tag list has
    // loaded, when there is nothing yet to prune against, and an empty
    // `lastConditions` would satisfy the negative assertion on its own.
    await waitFor(() => {
      expect(fieldsUsed()).toContain("project_id");
      expect(fieldsUsed()).not.toContain("tag_ids");
    });
  });

  it("stops trusting a remembered tag when the tag list cannot be loaded", async () => {
    // An id that cannot be checked may be hiding every task in the project.
    // Showing more than was asked for is recoverable; an unexplained empty
    // list is not.
    server.use(guildHttp.get("/tags/", () => new HttpResponse(null, { status: 500 })));
    rememberFilters({ tag_ids: [7] });
    section();

    await waitFor(() => {
      expect(fieldsUsed()).toContain("project_id");
      expect(fieldsUsed()).not.toContain("tag_ids");
    });
  });

  it("says so and still lists tasks when the URL names a preset that is gone", async () => {
    section({ routerSearch: { preset: "long-deleted" } });

    expect(await screen.findByText(/no longer exists/i)).toBeInTheDocument();
    // Still resolved to something, rather than 404ing the page.
    await waitFor(() => expect(fieldsUsed()).toContain("project_id"));
  });

  it("hides the curation affordances from someone who may not curate", async () => {
    server.use(
      guildHttp.get("/projects/:projectId/filter-presets/", () =>
        HttpResponse.json({ items: [], can_manage: false })
      )
    );
    section();
    await openFilters();

    await waitFor(() => expect(screen.queryByRole("button", { name: /save preset/i })).toBeNull());
    // The filters themselves are still theirs to set.
    expect(screen.getByRole("button", { name: /clear all/i })).toBeInTheDocument();
  });

  it("offers saving a preset, beside Clear all, to someone who may curate", async () => {
    section();
    await openFilters();

    expect(await screen.findByRole("button", { name: /save preset/i })).toBeInTheDocument();
  });

  it("offers updating the active preset only once its filters were tweaked", async () => {
    section();
    const user = await openFilters();

    expect(screen.queryByRole("button", { name: /update/i })).toBeNull();

    await toggleAssigneeToken(user, /^Unassigned$/);

    expect(await screen.findByRole("button", { name: /update/i })).toBeInTheDocument();
  });

  it("names the preset it would update", async () => {
    section();
    const user = await openFilters();
    await pickPreset(user, "Incomplete");

    await toggleAssigneeToken(user, /^Unassigned$/);

    expect(await screen.findByRole("button", { name: /update/i })).toHaveTextContent(/Incomplete/);
  });

  it("marks the preset modified, and offers a way back, once filters are tweaked", async () => {
    // Re-picking it in the select can't undo the edit — it is already the
    // selected value — so getting back is its own control.
    section();
    const user = await openFilters();
    await pickPreset(user, "Mine");

    expect(screen.queryByRole("button", { name: /reset to preset/i })).toBeNull();

    await toggleAssigneeToken(user, /^Unassigned$/);

    const combobox = await screen.findByRole("combobox", { name: /preset/i });
    await waitFor(() => expect(combobox).toHaveTextContent(/Mine.*modified/i));

    await user.click(await screen.findByRole("button", { name: /reset to preset/i }));

    await waitFor(() => expect(combobox).toHaveTextContent("Mine"));
    expect(combobox).not.toHaveTextContent(/modified/i);
  });

  it("offers the way back even to someone who may not curate presets", async () => {
    server.use(
      guildHttp.get("/projects/:projectId/filter-presets/", () =>
        HttpResponse.json({ items: buildDefaultFilterPresets(1), can_manage: false })
      )
    );
    section();
    const user = await openFilters();
    await pickPreset(user, "Mine");

    await toggleAssigneeToken(user, /^Unassigned$/);

    expect(await screen.findByRole("button", { name: /reset to preset/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /save preset/i })).toBeNull();
  });

  it("stops naming the preset in the URL once the filters are tweaked", async () => {
    // A link saying ?preset=mine has to show the preset, not one person's
    // edit of it.
    const { router } = section();
    const user = await openFilters();
    await pickPreset(user, "Mine");
    await waitFor(() =>
      expect((router.state.location.search as { preset?: string }).preset).toBe("mine")
    );

    await toggleAssigneeToken(user, /^Unassigned$/);

    await waitFor(() =>
      expect((router.state.location.search as { preset?: string }).preset).toBeUndefined()
    );
  });
});
