/**
 * The layout editor, worked as a manager works it: change the open layout in
 * the outline or on the canvas, see it at once, and nothing is stored until
 * Save, which sends only the layouts that changed.
 */
import { createEvent, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  buildCalendarEvent,
  buildDefaultTaskStatuses,
  buildPropertyDefinition,
  buildSavedLayoutSet,
  buildTask,
  buildTaskListResponse,
  buildToolLayoutSet,
} from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type {
  DetailLayoutWrite,
  ListLayoutWrite,
  ToolLayoutSetRead,
} from "@/api/generated/initiativeAPI.schemas";
import { calendarTarget, projectTarget, useToolLayouts } from "@/hooks/useToolLayouts";
import { MAX_PRESETS } from "@/lib/layouts/presets";
import type { LayoutNode } from "@/lib/layouts/tree";

import { eventDetail, taskDetail } from "./details";
import { LayoutEditor } from "./LayoutEditor";

const STATUSES = buildDefaultTaskStatuses(1);
const PROJECT = { id: 1, initiativeId: 1, statuses: STATUSES };
const PROJECT_DETAILS = [taskDetail(PROJECT)];
const CALENDAR_DETAILS = [eventDetail(1)];

type Write = ListLayoutWrite | DetailLayoutWrite;

/** Each request a save made, in order: a layout saved, one put back as
 *  shipped, or the list the project opens on. */
let sent: Array<{ save: Write } | { reset: string } | { opensOn: string }> = [];

/** What the save of `kind` stored. */
const saved = (kind: string) =>
  sent.flatMap((each) => ("save" in each && each.save.kind === kind ? [each.save] : []))[0]
    ?.definition as Record<string, unknown> | undefined;

/** The editor as its page holds it: on the project's layouts as read, which
 *  each save writes its answer over. With `calendar`, on the initiative
 *  calendar's instead. */
const editor = (kind: string, onClose = vi.fn(), set = buildToolLayoutSet(), calendar = false) => {
  server.use(communityHttp.get("/layouts/", () => HttpResponse.json(set)));
  const target = calendar ? calendarTarget(1) : projectTarget(1);
  const Page = () => {
    const read = useToolLayouts(target).data;
    return read ? (
      <LayoutEditor
        target={target}
        initiativeId={1}
        project={calendar ? undefined : PROJECT}
        details={calendar ? CALENDAR_DETAILS : PROJECT_DETAILS}
        set={read}
        initialKind={kind}
        onClose={onClose}
      />
    ) : null;
  };
  renderPage(Page);
  return { user: userEvent.setup(), onClose };
};

/** A pointer event from one pointer: jsdom's stand-in carries no id. */
const firePointer = (
  type: "pointerDown" | "pointerUp" | "pointerCancel",
  target: Element | Window,
  pointerId: number
) => {
  const event = createEvent[type](target);
  Object.defineProperty(event, "pointerId", { value: pointerId });
  fireEvent(target, event);
};

const outline = () => screen.findByRole("navigation", { name: /outline/i });
const canvas = () => screen.findByRole("region", { name: /preview/i });

beforeEach(() => {
  sent = [];
  server.use(
    communityHttp.get("/tasks/:taskId", () =>
      HttpResponse.json({
        ...buildTask({
          id: 7,
          project_id: 1,
          title: "Draw the map",
          task_status_id: STATUSES[0].id,
        }),
        description: "Every road, to scale.",
      })
    ),
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
    communityHttp.put("/layouts/", async ({ request }) => {
      const body = (await request.json()) as Write;
      sent.push({ save: body });
      return HttpResponse.json(buildSavedLayoutSet(buildToolLayoutSet(), body));
    }),
    communityHttp.delete("/layouts/:kind", ({ params }) => {
      sent.push({ reset: String(params.kind) });
      return HttpResponse.json(buildToolLayoutSet());
    }),
    communityHttp.put("/layouts/default", async ({ request }) => {
      const { kind } = (await request.json()) as { kind: string };
      sent.push({ opensOn: kind });
      return HttpResponse.json<ToolLayoutSetRead>(buildToolLayoutSet());
    })
  );
});

describe("LayoutEditor", () => {
  it("takes a field off the card at once, and stores it only on Save", async () => {
    const { user } = editor("board");
    expect(await within(await canvas()).findByText(/priority: medium/i)).toBeInTheDocument();

    await user.click(within(await outline()).getByRole("button", { name: /hide priority/i }));

    expect(within(await canvas()).queryByText(/priority: medium/i)).not.toBeInTheDocument();
    expect(sent).toEqual([]);
    await user.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(JSON.stringify(saved("board")?.card)).not.toContain('"priority"');
    // The other layouts are not sent, so they keep their dates.
    expect(sent).toHaveLength(1);
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

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(saved("table")?.columns).toEqual([
      "title",
      "startDate",
      "dueDate",
      "priority",
      "tags",
      "comments",
      "property:12",
    ]);
  });

  it("changes nothing while a save is under way, and still asks before leaving", async () => {
    let answer = () => {};
    server.use(
      communityHttp.put("/layouts/", async ({ request }) => {
        const body = (await request.json()) as Write;
        await new Promise<void>((resolve) => {
          answer = resolve;
        });
        return HttpResponse.json(buildSavedLayoutSet(buildToolLayoutSet(), body));
      })
    );
    const { user, onClose } = editor("board");
    await within(await canvas()).findByText(/priority: medium/i);

    await user.click(within(await outline()).getByRole("button", { name: /hide priority/i }));
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(await screen.findByRole("button", { name: /saving/i })).toBeDisabled();
    expect(within(await outline()).getByRole("button", { name: /hide tags/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^undo$/i })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /close the editor/i }));
    expect(await screen.findByText(/still being saved/i)).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: /keep editing/i }));

    answer();
    expect(await screen.findByRole("button", { name: /^save$/i })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /close the editor/i }));
    expect(onClose).toHaveBeenCalled();
  });

  it("adds a plug-in's field to a table as a column", async () => {
    server.use(
      communityHttp.get("/plugins/", () =>
        HttpResponse.json({
          items: [
            {
              id: 3,
              name: "CI",
              enabled: true,
              definition: {
                fields: [{ key: "ci.state", name: { en: "Build" }, kind: "badge", on: ["task"] }],
              },
              item_initiatives: [1],
              item_fields: ["ci.state"],
              item_parts: [],
              item_actions: [],
            },
          ],
        })
      )
    );
    const { user } = editor("table");

    await user.click(await within(await outline()).findByRole("button", { name: /^add$/i }));
    expect(await screen.findByText("CI")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Build" }));
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(sent).toHaveLength(1));
    expect((saved("table")?.columns as string[] | undefined)?.at(-1)).toBe("plugin:3:ci.state");
  });

  it("opens the project on the open list as a change of its own", async () => {
    const { user } = editor("board");
    await outline();

    await user.click(screen.getByRole("switch", { name: /opens first/i }));
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(sent).toEqual([{ opensOn: "board" }]));
  });

  it("adds a preset to the open list beside the shipped ones, sorted as chosen", async () => {
    const { user } = editor("table");
    await outline();

    await user.click(screen.getByRole("button", { name: /add preset/i }));
    const dialog = await screen.findByRole("dialog", { name: /add a preset/i });
    await user.type(within(dialog).getByLabelText(/^name$/i), "Overdue first");
    await user.click(within(dialog).getByRole("combobox", { name: /sort by/i }));
    await user.click(await screen.findByRole("option", { name: /due date/i }));
    await user.click(within(dialog).getByRole("switch", { name: /descending/i }));
    await user.click(within(dialog).getByRole("button", { name: /^done$/i }));
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(saved("table")).toBeDefined());
    const presets = saved("table")?.presets as Record<string, unknown>[];
    // The shipped ones are kept by slug alone, so each reader still reads
    // their names in their own words.
    expect(presets.map((preset) => [preset.slug, preset.name])).toEqual([
      ["incomplete", undefined],
      ["unassigned", undefined],
      ["mine", undefined],
      ["overdue-first", "Overdue first"],
    ]);
    expect(presets[3].sort).toEqual([{ field: "due_date", dir: "desc" }]);
  });

  it("adds no preset past the most a list may offer", async () => {
    const presets = Array.from({ length: MAX_PRESETS }, (_, index) => ({
      name: `Preset ${index}`,
      slug: `preset-${index}`,
    }));
    editor(
      "table",
      vi.fn(),
      buildToolLayoutSet({
        layouts: [
          {
            kind: "table",
            is_default: true,
            definition: { presets },
            updated_at: "2026-10-01T12:00:00.000Z",
          },
        ],
      })
    );
    await outline();

    expect(screen.getByRole("button", { name: /add preset/i })).toBeDisabled();
    expect(screen.getByText(/at most 20 presets/i)).toBeInTheDocument();
  });

  it("takes a preset off the open list and keeps the rest in order", async () => {
    const { user } = editor("board");
    await outline();

    await user.click(screen.getByRole("button", { name: /move mine up/i }));
    await user.click(screen.getByRole("button", { name: /remove incomplete/i }));
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(saved("board")).toBeDefined());
    const presets = saved("board")?.presets as { slug: string }[] | undefined;
    expect(presets?.map((preset) => preset.slug)).toEqual(["mine", "unassigned"]);
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

  describe("on the canvas", () => {
    it("adds a part before the one pointed at", async () => {
      const { user } = editor("board");
      await user.hover(await within(await canvas()).findByText(/priority: medium/i));

      // Clicked where it is, as the pointer reaches it from the part.
      fireEvent.click(screen.getByRole("button", { name: /add before priority/i }));
      const picker = await screen.findByRole("dialog", { name: "Add" });
      await user.click(within(picker).getByRole("button", { name: "Group" }));
      await user.click(screen.getByRole("button", { name: /^save$/i }));

      await waitFor(() => expect(sent).toHaveLength(1));
      const card = saved("board")?.card;
      // The row holding Priority starts with the group, Priority after it.
      expect(
        (
          (card as LayoutNode | undefined)?.children?.[1] as LayoutNode | undefined
        )?.children?.slice(0, 2)
      ).toEqual([
        { type: "stack", props: { align: "start" }, children: [] },
        { type: "field", props: { field: "priority" } },
      ]);
    });

    it("adds a column after the one pointed at", async () => {
      const { user } = editor("table");
      const header = await within(await canvas()).findByRole("columnheader", { name: /priority/i });
      await user.hover(within(header).getByText(/priority/i));

      fireEvent.click(screen.getByRole("button", { name: /add after priority/i }));
      const picker = await screen.findByRole("dialog", { name: "Add" });
      await user.click(within(picker).getByRole("button", { name: "Effort" }));
      await user.click(screen.getByRole("button", { name: /^save$/i }));

      await waitFor(() => expect(sent).toHaveLength(1));
      expect(saved("table")?.columns).toEqual([
        "title",
        "startDate",
        "dueDate",
        "priority",
        "property:12",
        "tags",
        "comments",
      ]);
    });

    /** Grabs the selected part's handle on the canvas, with one pointer. */
    const grab = async (name: RegExp, pointer = 1) => {
      const nav = await outline();
      const handle = screen
        .getAllByRole("button", { name })
        .find((button) => !nav.contains(button)) as Element;
      firePointer("pointerDown", handle, pointer);
    };
    /** What jsdom cannot work out: the element under the pointer. */
    const under = (element: Element, run: () => void) => {
      const was = document.elementsFromPoint;
      document.elementsFromPoint = () => [element];
      try {
        run();
      } finally {
        document.elementsFromPoint = was;
      }
    };

    it("lets a drag go when an undo changes the card under it", async () => {
      const { user } = editor("board");
      const drawn = await canvas();
      await user.click(within(await outline()).getByRole("button", { name: /hide tags/i }));
      await user.click(await within(drawn).findByText(/priority: medium/i));
      await grab(/move priority/i);

      await user.keyboard("{Control>}z{/Control}");
      under(within(drawn).getByText("Draw the map"), () => firePointer("pointerUp", window, 1));

      // The undo stands, and nothing moved after it.
      expect(screen.getByRole("button", { name: /^save$/i })).toBeDisabled();
    });

    it("moves a part only for the pointer that took hold of it", async () => {
      const { user } = editor("board");
      const drawn = await canvas();
      await user.click(await within(drawn).findByText(/priority: medium/i));
      const title = within(drawn).getByText("Draw the map");

      await grab(/move priority/i, 1);
      under(title, () => firePointer("pointerUp", window, 2));
      firePointer("pointerCancel", window, 1);
      under(title, () => firePointer("pointerUp", window, 1));

      expect(screen.getByRole("button", { name: /^save$/i })).toBeDisabled();
    });

    it("takes a part into a group added empty", async () => {
      const { user } = editor("board");
      const drawn = await canvas();
      await user.click(await within(drawn).findByText(/priority: medium/i));
      await user.click(within(await outline()).getByRole("button", { name: /^add$/i }));
      const picker = await screen.findByRole("dialog", { name: "Add" });
      await user.click(within(picker).getByRole("button", { name: "Group" }));
      // Adding put the group after Priority and selected it; Priority again.
      await user.click(within(drawn).getByText(/priority: medium/i));
      const [empty] = within(drawn).getAllByText(/drop a part here/i);
      await user.hover(empty);
      expect(screen.getByRole("button", { name: /add to group/i })).toBeInTheDocument();

      await grab(/move priority/i);
      under(empty, () => firePointer("pointerUp", window, 1));
      await user.click(screen.getByRole("button", { name: /^save$/i }));

      await waitFor(() => expect(sent).toHaveLength(1));
      const card = saved("board")?.card;
      expect(
        ((card as LayoutNode | undefined)?.children?.[1] as LayoutNode | undefined)?.children?.[0]
      ).toEqual({
        type: "stack",
        props: { align: "start" },
        children: [{ type: "field", props: { field: "priority" } }],
      });
    });

    it("moves the selected part where it is dragged", async () => {
      const { user } = editor("board");
      const drawn = await canvas();
      await user.click(await within(drawn).findByText(/priority: medium/i));
      const title = within(drawn).getByText("Draw the map");
      const nav = await outline();
      const handle = screen
        .getAllByRole("button", { name: /move priority/i })
        .find((button) => !nav.contains(button));

      // Dropped on the title's upper half: before it. jsdom lays nothing out,
      // so what is under the pointer is said here.
      const under = document.elementsFromPoint;
      document.elementsFromPoint = () => [title];
      try {
        fireEvent.pointerDown(handle as Element);
        fireEvent.pointerUp(window, { clientX: 0, clientY: 0 });
      } finally {
        document.elementsFromPoint = under;
      }
      await user.click(screen.getByRole("button", { name: /^save$/i }));

      await waitFor(() => expect(sent).toHaveLength(1));
      const card = saved("board")?.card;
      expect(
        (
          (card as LayoutNode | undefined)?.children?.[0] as LayoutNode | undefined
        )?.children?.slice(0, 2)
      ).toEqual([
        { type: "field", props: { field: "priority" } },
        { type: "field", props: { field: "title" } },
      ]);
    });
  });

  describe("the task's detail", () => {
    it("moves a field taken off it to More fields, and stores the layout whole", async () => {
      const { user } = editor("task");
      expect(await within(await canvas()).findByDisplayValue("Draw the map")).toBeInTheDocument();

      await user.click(
        within(await outline()).getByRole("button", { name: /move tags to more fields/i })
      );

      expect(within(await outline()).getByText("More fields")).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: /^save$/i }));
      await waitFor(() => expect(sent).toHaveLength(1));
      expect(JSON.stringify(saved("task")?.side)).not.toContain('"tags"');
      expect(JSON.stringify(saved("task"))).not.toContain('"order"');
    });

    it("adds a section where it was asked for, titled as typed", async () => {
      const { user } = editor("task");

      await user.click(
        await within(await outline()).findByRole("button", { name: "Side", pressed: false })
      );
      await user.click(within(await outline()).getByRole("button", { name: /^add$/i }));
      await user.click(await screen.findByRole("button", { name: "Section" }));
      await user.type(screen.getByLabelText(/^title$/i), "Planning{Enter}");
      await user.click(screen.getByRole("button", { name: /^save$/i }));

      await waitFor(() => expect(sent).toHaveLength(1));
      expect((saved("task")?.side as LayoutNode[] | undefined)?.at(-1)).toEqual({
        type: "section",
        props: { title: "Planning" },
        children: [],
      });
    });

    it("goes back to the shipped layout", async () => {
      const { user } = editor(
        "task",
        vi.fn(),
        buildToolLayoutSet({
          layouts: [
            {
              kind: "task",
              definition: { main: [{ type: "comments" }] },
              updated_at: "2026-10-01T12:00:00.000Z",
            },
          ],
        })
      );

      await user.click(await screen.findByRole("button", { name: /use the shipped layout/i }));
      await user.click(screen.getByRole("button", { name: /^save$/i }));

      await waitFor(() => expect(sent).toEqual([{ reset: "task" }]));
    });
  });

  describe("the calendar's event detail", () => {
    it("lays out the event detail alone, sending it and nothing else", async () => {
      const event = buildCalendarEvent({ id: 9, title: "Standup", location: "Room 2" });
      server.use(
        communityHttp.get("/calendar-entries/", () =>
          HttpResponse.json({ events: [event], tasks: [], task_occurrences: [] })
        ),
        communityHttp.get("/calendar-events/:eventId", () => HttpResponse.json(event))
      );
      const { user } = editor("", vi.fn(), buildToolLayoutSet({ tool: "calendar" }), true);
      expect(await within(await canvas()).findByDisplayValue("Room 2")).toBeInTheDocument();

      await user.click(
        within(await outline()).getByRole("button", { name: /move location to more fields/i })
      );
      await user.click(screen.getByRole("button", { name: /^save$/i }));

      await waitFor(() => expect(sent).toHaveLength(1));
      expect(JSON.stringify(saved("calendar_event"))).not.toContain('"location"');
    });
  });
});
