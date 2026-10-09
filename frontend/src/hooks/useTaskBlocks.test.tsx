/**
 * Which plug-in blocks a screen's tasks are offered, and how their rows are read:
 * once per block for every task the screen has loaded, never once per card.
 */
import { fireEvent, screen, within } from "@testing-library/react";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildTask } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { CommunityPluginRead, TaskListRead } from "@/api/generated/initiativeAPI.schemas";

import { type ListedProject, useTaskBlocks } from "./useTaskBlocks";

let plugins: Partial<CommunityPluginRead>[] = [];

vi.mock("@/hooks/useCommunityPlugins", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useCommunityPlugins")>()),
  useCommunityPlugins: () => ({ data: { items: plugins } }),
}));

const block = (id: string, areas: string[], template: string, more: object = {}) => ({
  id,
  areas,
  name: { en: id },
  template,
  ...more,
});

const timer = {
  id: 3,
  name: "Acme",
  enabled: true,
  definition: {
    service: { public_id: "acme.timer" },
    endpoints: [
      {
        id: "plugin.acme.timer.timers.read",
        returns: [
          { key: "task_id", type: "int", list: true },
          { key: "label", type: "string", list: true },
        ],
      },
    ],
    blocks: [
      block(
        "timer",
        ["task.card.inline", "task.page.aside"],
        `<span>{{ answer != null ? answer.label : strings.idle }}</span><button action="timers.start">{{ strings.start }}</button>`,
        {
          endpoint: "plugin.acme.timer.timers.read",
          actions: ["plugin.acme.timer.timers.start"],
          strings: { idle: { en: "Idle" }, start: { en: "Start" } },
        }
      ),
      block("deal", ["task.card.inline"], "<span>Deal</span>", {
        project_listing: "WY4WAN93PFP3X4",
      }),
      block("aside", ["task.page.aside"], "<span>Aside only</span>"),
      block("elsewhere", ["task.card.inline"], "<span>Another initiative</span>"),
    ],
  },
  block_access: [
    { block_id: "timer", openable_initiatives: [5] },
    { block_id: "deal", openable_initiatives: [5] },
    { block_id: "aside", openable_initiatives: [5] },
    { block_id: "elsewhere", openable_initiatives: [6] },
  ],
} as unknown as CommunityPluginRead;

const Board = ({ project, tasks }: { project: ListedProject; tasks: TaskListRead[] }) => {
  const blocks = useTaskBlocks("task.card", { project, taskIds: tasks.map((task) => task.id) });
  return (
    <>
      {tasks.map((task) => (
        <div key={task.id} data-testid={`card-${task.id}`}>
          {blocks?.("inline", { task }, undefined)}
        </div>
      ))}
    </>
  );
};

/** Answers each rows call with a row for task 1 only, and keeps what each asked for. */
const answerRows = () => {
  const asked: { block: string; taskIds: number[] }[] = [];
  server.use(
    communityHttp.post("/plugins/:pluginId/blocks/:blockId/rows", async ({ params, request }) => {
      const { task_ids } = (await request.json()) as { task_ids: number[] };
      asked.push({ block: String(params.blockId), taskIds: task_ids });
      return HttpResponse.json({
        rows: { 1: { task_id: 1, label: "Running" } },
        fetched_at: "2026-10-09T00:00:00Z",
        cached: false,
      });
    })
  );
  return asked;
};

const tasks = [buildTask({ id: 1 }), buildTask({ id: 2 })];

beforeEach(() => {
  plugins = [timer, { ...timer, id: 4, enabled: false }];
});

describe("useTaskBlocks", () => {
  it("offers the area's blocks for the initiative and the project's listing, reading each once", async () => {
    const asked = answerRows();
    renderWithProviders(<Board project={{ initiative_id: 5, listing_uid: null }} tasks={tasks} />);

    const first = within(screen.getByTestId("card-1"));
    expect(await first.findByText("Running")).toBeInTheDocument();
    expect(within(screen.getByTestId("card-2")).getByText("Idle")).toBeInTheDocument();
    expect(first.getByRole("group", { name: "timer, from Acme" })).toBeInTheDocument();
    // Not confined to this project's listing, not in this area, not in this initiative,
    // and not from a turned-off install.
    expect(screen.queryByText("Deal")).toBeNull();
    expect(screen.queryByText("Aside only")).toBeNull();
    expect(screen.queryByText("Another initiative")).toBeNull();
    expect(first.getAllByRole("group")).toHaveLength(1);
    // One call for the board, naming every task it loaded.
    expect(asked).toEqual([{ block: "timer", taskIds: [1, 2] }]);
  });

  it("offers a block confined to a listing on that listing's projects", async () => {
    answerRows();
    renderWithProviders(
      <Board project={{ initiative_id: 5, listing_uid: "WY4WAN93PFP3X4" }} tasks={tasks} />
    );
    expect(await within(screen.getByTestId("card-1")).findByText("Deal")).toBeInTheDocument();
  });

  it("draws the row an action answers for its task", async () => {
    answerRows();
    const ran: { action: string; taskId: number }[] = [];
    server.use(
      communityHttp.post(
        "/plugins/:pluginId/blocks/:blockId/actions/:action",
        async ({ params, request }) => {
          const { task_id } = (await request.json()) as { task_id: number };
          ran.push({ action: String(params.action), taskId: task_id });
          return HttpResponse.json({ row: { task_id, label: "Started" } });
        }
      )
    );
    renderWithProviders(<Board project={{ initiative_id: 5, listing_uid: null }} tasks={tasks} />);

    const second = within(screen.getByTestId("card-2"));
    fireEvent.click(await second.findByRole("button", { name: "Start" }));
    expect(await second.findByText("Started")).toBeInTheDocument();
    expect(ran).toEqual([{ action: "timers.start", taskId: 2 }]);
    expect(within(screen.getByTestId("card-1")).getByText("Running")).toBeInTheDocument();
  });
});
