import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { buildTask } from "@/__tests__/factories";
import i18n from "@/__tests__/helpers/i18n-test";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { TaskListRead } from "@/api/generated/initiativeAPI.schemas";
import { pluginFieldId, pluginFields, pluginsOnItems } from "@/lib/views/plugins";
import { taskFields } from "@/lib/views/tasks";
import { drawnFields, type ViewNode, ViewTree } from "@/lib/views/tree";
import type { TranslateFn } from "@/types/i18n";

const definition = {
  fields: [
    { key: "ci.state", name: { en: "CI" }, kind: "badge", on: ["task"], tone: "positive" },
    { key: "ci.url", name: { en: "Build" }, kind: "link", on: ["task"] },
    { key: "event.only", name: { en: "Elsewhere" }, kind: "text", on: ["calendar_event"] },
  ],
  parts: [
    {
      id: "builds",
      name: { en: "Builds" },
      on: ["task"],
      tree: {
        type: "section",
        props: { title: { en: "Builds" } },
        children: [
          { type: "field", props: { field: "ci.url" } },
          { type: "button", props: { action: "rerun" } },
          { type: "button", props: { action: "purge" } },
        ],
      },
    },
  ],
  actions: [
    {
      id: "rerun",
      name: { en: "Run again" },
      on: ["task"],
      confirm: { en: "Run the build again?" },
    },
    { id: "purge", name: { en: "Purge" }, on: ["task"] },
  ],
};

const install = {
  id: 3,
  enabled: true,
  definition,
  item_initiatives: [7],
  item_actions: ["rerun"],
};

const task = buildTask({
  id: 41,
  plugin_values: [
    { plugin_id: 3, key: "ci.state", value: { text: "passing" } },
    { plugin_id: 3, key: "ci.url", value: { url: "https://ci.example/41", text: "#41" } },
  ],
});

const draw = (card: ViewNode, item: TaskListRead = task) => {
  const plugins = pluginsOnItems([install], 7);
  const view = {
    fields: taskFields([], pluginFields(plugins, "en")),
    plugins,
    variant: "card" as const,
    isHidden: () => false,
    env: {
      t: i18n.getFixedT(null, ["projects", "dates", "relations"]) as TranslateFn,
      communityPath: (path: string) => path,
      taskHref: ({ id }: TaskListRead) => `/tasks/${id}`,
    },
  };
  return renderWithProviders(<ViewTree node={card} item={item} view={view} />);
};

describe("pluginsOnItems", () => {
  it("keeps what an install declares on tasks where the reader meets it", () => {
    const plugins = pluginsOnItems(
      [
        install,
        { ...install, id: 4, enabled: false },
        { ...install, id: 5, item_initiatives: [8] },
      ],
      7
    );

    expect([...plugins.keys()]).toEqual([3]);
    const plugin = plugins.get(3);
    expect([...(plugin?.fields.keys() ?? [])]).toEqual(["ci.state", "ci.url"]);
    // Only the actions the server says this reader may run.
    expect([...(plugin?.actions.keys() ?? [])]).toEqual(["rerun"]);
  });
});

describe("a plug-in on a card", () => {
  it("draws the fields and parts the card places, and nothing it does not", async () => {
    draw({
      type: "card",
      children: [
        { type: "field", props: { field: pluginFieldId(3, "ci.state") } },
        { type: "plugin", props: { plugin: 3, part: "builds" } },
        { type: "plugin", props: { plugin: 9, part: "builds" } },
      ],
    });

    expect(screen.getByText("passing")).toBeInTheDocument();
    expect(screen.getByText("Builds")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /#41/ })).toHaveAttribute(
      "href",
      "https://ci.example/41"
    );
    expect(screen.getByRole("button", { name: "Run again" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Purge" })).toBeNull();
  });

  it("draws nothing for a value of the wrong shape or a link that is not the web", () => {
    draw(
      {
        type: "card",
        children: [
          { type: "field", props: { field: pluginFieldId(3, "ci.state") } },
          { type: "field", props: { field: pluginFieldId(3, "ci.url") } },
        ],
      },
      buildTask({
        plugin_values: [
          { plugin_id: 3, key: "ci.state", value: "passing" },
          { plugin_id: 3, key: "ci.url", value: { url: "javascript:alert(1)" } },
        ],
      })
    );

    expect(screen.queryByText("CI")).toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("asks first, then runs the action on the task", async () => {
    let ran: unknown = null;
    server.use(
      http.post("/api/v1/c/1/plugins/3/actions/rerun", async ({ request }) => {
        ran = await request.json();
        return HttpResponse.json({ values: {} });
      })
    );
    draw({ type: "card", children: [{ type: "plugin", props: { plugin: 3, part: "builds" } }] });

    await userEvent.click(screen.getByRole("button", { name: "Run again" }));
    expect(await screen.findByText("Run the build again?")).toBeInTheDocument();
    expect(ran).toBeNull();
    await userEvent.click(
      screen.getAllByRole("button", { name: "Run again" }).at(-1) as HTMLElement
    );

    await waitFor(() => expect(ran).toEqual({ entity_type: "task", entity_id: 41 }));
  });

  it("offers to hide only the fields the card draws", () => {
    const fields = taskFields([], pluginFields(pluginsOnItems([install], 7), "en"));
    const card: ViewNode = {
      type: "card",
      children: [
        { type: "field", props: { field: "title" } },
        { type: "field", props: { field: pluginFieldId(3, "ci.url") } },
      ],
    };

    expect(drawnFields(card, fields).map((field) => field.id)).toEqual([
      "title",
      pluginFieldId(3, "ci.url"),
    ]);
  });
});
