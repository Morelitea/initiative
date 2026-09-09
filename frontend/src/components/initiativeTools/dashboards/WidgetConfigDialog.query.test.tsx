import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { DefinitionWidget } from "@/lib/widgets/definition";

const renderWidget = vi.hoisted(() => vi.fn());
const readWidgetMeta = vi.hoisted(() => vi.fn());
vi.mock("@/lib/widgets/runtime/host", () => ({ renderWidget, readWidgetMeta }));

import { WidgetConfigDialog } from "./WidgetConfigDialog";

const BUILT_SQL = "SELECT count(*) AS count FROM tasks";
const SHIPPED_SQL = "SELECT priority, count(*) AS tasks FROM tasks GROUP BY priority";

const VOCABULARY = {
  datasets: ["tasks", "projects"],
  functions: ["count", "date_trunc", "lower"],
};

const FIELD = (name: string, type: string) => ({
  name,
  type,
  kind: "text",
  ops: ["eq"],
  multiple: false,
  sortable: true,
  options: [],
});

/** Every request the two tabs make, counted so a test can say what was asked. */
const asked = { build: 0, describe: 0 };

const serve = () => {
  asked.build = 0;
  asked.describe = 0;
  server.use(
    http.get("/api/v1/query/vocabulary", () => HttpResponse.json(VOCABULARY)),
    http.get("/api/v1/fields/:dataset", ({ params }) =>
      HttpResponse.json({
        dataset: params.dataset,
        fields:
          params.dataset === "tasks"
            ? [FIELD("title", "text"), FIELD("due_date", "date")]
            : [FIELD("name", "text")],
      })
    ),
    guildHttp.post("/query/build", () => {
      asked.build += 1;
      return HttpResponse.json({ sql: BUILT_SQL, columns: [], relations: ["tasks"] });
    }),
    guildHttp.post("/query/describe", () => {
      asked.describe += 1;
      return HttpResponse.json({
        columns: [{ name: "tasks", type: "number" }],
        relations: ["tasks"],
      });
    }),
    guildHttp.post("/query", () =>
      HttpResponse.json({ columns: [], rows: [], truncated: false, relations: [] })
    )
  );
};

const onSave = vi.fn();

beforeEach(() => {
  onSave.mockReset();
  renderWidget.mockReset();
  readWidgetMeta.mockReset();
  renderWidget.mockResolvedValue({ ok: true, spec: { scene: { kind: "empty" } } });
  readWidgetMeta.mockResolvedValue({ name: { en: "Total" } });
  serve();
});

const widget = (binding: Record<string, unknown>): DefinitionWidget => ({
  id: "w1",
  type: "stat",
  grid: { x: 0, y: 0, w: 6, h: 4 },
  binding: binding as DefinitionWidget["binding"],
});

const mount = (which: DefinitionWidget) =>
  renderWithProviders(
    <WidgetConfigDialog
      widget={which}
      catalog={{ widgets: [], presets: [] }}
      initiativeId={7}
      open
      onOpenChange={() => {}}
      onSave={onSave}
    />,
    { guilds: { activeGuildId: 2 } }
  );

const sqlBox = () => screen.getByRole("textbox", { name: /statement/i });

describe("a statement that arrived without a description", () => {
  it("opens on SQL, showing what it has", async () => {
    mount(widget({ source: "query", sql: SHIPPED_SQL }));
    await waitFor(() => expect(sqlBox()).toHaveValue(SHIPPED_SQL));
  });

  it("is not replaced by the builder's default just by being looked at", async () => {
    // The bug: the builder used to initialise on its default spec, build that,
    // and write it over the author's statement before anybody touched anything.
    mount(widget({ source: "query", sql: SHIPPED_SQL }));
    await waitFor(() => expect(sqlBox()).toHaveValue(SHIPPED_SQL));

    expect(asked.build).toBe(0);
  });

  it("says the builder is not driving it, and offers to start over", async () => {
    const user = userEvent.setup();
    mount(widget({ source: "query", sql: SHIPPED_SQL }));

    await user.click(await screen.findByRole("tab", { name: /build/i }));
    expect(await screen.findByRole("button", { name: /build a new query/i })).toBeInTheDocument();
  });
});

describe("a statement somebody builds", () => {
  it("is written by the server from what was clicked", async () => {
    const user = userEvent.setup();
    mount(widget({ source: "query" }));

    await user.click(await screen.findByRole("tab", { name: /sql/i }));
    await waitFor(() => expect(sqlBox()).toHaveValue(BUILT_SQL));
  });
});

describe("a statement somebody writes", () => {
  it("drops the description behind it, because it is no longer true of it", async () => {
    const user = userEvent.setup();
    mount(widget({ source: "query", sql: SHIPPED_SQL }));

    await waitFor(() => expect(sqlBox()).toHaveValue(SHIPPED_SQL));
    await user.click(sqlBox());
    await user.type(sqlBox(), " LIMIT 5");

    await waitFor(() => expect(sqlBox()).toHaveValue(`${SHIPPED_SQL} LIMIT 5`));
    // Never handed back to the builder to re-derive: the text is what is stored.
    expect(asked.build).toBe(0);
  });

  it("is checked by the server, and says what it would return", async () => {
    mount(widget({ source: "query", sql: SHIPPED_SQL }));

    await waitFor(() => expect(asked.describe).toBeGreaterThan(0));
    expect(await screen.findByText("Returns: tasks")).toBeInTheDocument();
  });
});

describe("completion", () => {
  /** A widget already on the SQL tab, so typing continues the stored text
   *  rather than the statement the builder would have written. */
  const halfWritten = () => widget({ source: "query", sql: "SELECT " });

  it("offers the names the server says exist", async () => {
    const user = userEvent.setup();
    mount(halfWritten());

    await user.click(sqlBox());
    await user.type(sqlBox(), "ti");
    // `title` is a field of tasks, which the server named in the catalog.
    expect(await screen.findByRole("button", { name: /title/i })).toBeInTheDocument();
  });

  it("offers a dataset and a function too, not only fields", async () => {
    const user = userEvent.setup();
    mount(halfWritten());

    await user.click(sqlBox());
    await user.type(sqlBox(), "co");
    expect(await screen.findByRole("button", { name: /count/i })).toBeInTheDocument();
  });

  it("puts the chosen name in place of the word being typed", async () => {
    const user = userEvent.setup();
    mount(halfWritten());

    await user.click(sqlBox());
    await user.type(sqlBox(), "ti");
    await user.click(await screen.findByRole("button", { name: /title/i }));

    await waitFor(() => expect(sqlBox()).toHaveValue("SELECT title"));
  });

  it("offers nothing once a name is written in full", async () => {
    const user = userEvent.setup();
    mount(halfWritten());

    await user.click(sqlBox());
    await user.type(sqlBox(), "title");
    await waitFor(() => expect(sqlBox()).toHaveValue("SELECT title"));
    expect(screen.queryByRole("button", { name: /^title$/i })).not.toBeInTheDocument();
  });
});
