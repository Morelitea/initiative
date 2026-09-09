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
  tokens: ["me"],
};

const FIELD = (name: string, type: string, kind = "text") => ({
  name,
  type,
  kind,
  ops: ["eq"],
  multiple: false,
  sortable: true,
  options: [],
});

/** Every request the two tabs make, counted so a test can say what was asked. */
const asked = { build: 0, describe: 0 };

/** The last description the builder sent, so a test can read what was clicked. */
const described: { build: Record<string, unknown> | null } = { build: null };

const serve = () => {
  asked.build = 0;
  asked.describe = 0;
  described.build = null;
  server.use(
    http.get("/api/v1/query/vocabulary", () => HttpResponse.json(VOCABULARY)),
    http.get("/api/v1/fields/:dataset", ({ params }) =>
      HttpResponse.json({
        dataset: params.dataset,
        fields:
          params.dataset === "tasks"
            ? [
                FIELD("title", "text"),
                FIELD("due_date", "date"),
                FIELD("created_by", "reference", "member"),
              ]
            : [FIELD("name", "text")],
        relations: params.dataset === "tasks" ? [{ name: "project", dataset: "projects" }] : [],
      })
    ),
    guildHttp.post("/query/build", async ({ request }) => {
      asked.build += 1;
      described.build = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json({ sql: BUILT_SQL, columns: [], relations: ["tasks"] });
    }),
    guildHttp.post("/query/describe", async ({ request }) => {
      asked.describe += 1;
      const body = (await request.json()) as { sql: string };
      // The validator refuses a name the registry does not have; everything
      // else in these tests is a statement it accepts.
      if (body.sql.includes("nope")) {
        return HttpResponse.json({ detail: "QUERY_UNKNOWN_FIELD" }, { status: 400 });
      }
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

describe("narrowing what a tile is about", () => {
  it("starts with nothing, which is every row", async () => {
    mount(widget({ source: "query" }));
    expect(await screen.findByText(/no filters/i)).toBeInTheDocument();
  });

  it("sends what was clicked as part of the description", async () => {
    const user = userEvent.setup();
    mount(widget({ source: "query" }));

    await user.click(await screen.findByRole("button", { name: /add filter/i }));

    await waitFor(() => {
      const where = described.build?.where as { field: string }[] | undefined;
      expect(where?.[0]?.field).toBe("title");
    });
  });

  it("offers nothing to filter on where the dataset named no fields", async () => {
    // A catalog that could not be read looks the same as a dataset with
    // nothing comparable in it, and adding a condition in either case would
    // store one naming no field at all.
    server.use(
      http.get("/api/v1/fields/:dataset", ({ params }) =>
        HttpResponse.json({ dataset: params.dataset, fields: [] })
      )
    );
    mount(widget({ source: "query" }));

    expect(await screen.findByText(/nothing to filter on/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /add filter/i })).not.toBeInTheDocument();
  });

  it("offers the reader in a picker that holds people", async () => {
    const user = userEvent.setup();
    mount(widget({ source: "query" }));

    await user.click(await screen.findByRole("button", { name: /add filter/i }));
    // The first field is text; the person field is what has a member picker.
    await user.click(await screen.findByRole("combobox", { name: /field/i }));
    await user.click(await screen.findByRole("option", { name: /created by/i }));

    await user.click(await screen.findByRole("combobox", { name: /value/i }));
    expect(await screen.findByRole("option", { name: /^me$/i })).toBeInTheDocument();
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

  it("offers the reader, which is a name no dataset holds", async () => {
    const user = userEvent.setup();
    mount(halfWritten());

    await user.click(sqlBox());
    await user.type(sqlBox(), "m");
    expect(await screen.findByRole("button", { name: /^me$/i })).toBeInTheDocument();
  });

  it("puts the chosen name in place of the word being typed", async () => {
    const user = userEvent.setup();
    mount(halfWritten());

    await user.click(sqlBox());
    await user.type(sqlBox(), "ti");
    await user.click(await screen.findByRole("button", { name: /title/i }));

    await waitFor(() => expect(sqlBox()).toHaveValue("SELECT title"));
  });

  it("offers what the statement's dataset can be read alongside", async () => {
    const user = userEvent.setup();
    mount(widget({ source: "query", sql: "SELECT title FROM tasks WHERE " }));

    await user.click(sqlBox());
    await user.type(sqlBox(), "proj");
    // The relation, which says what it reaches — beside the `projects` dataset,
    // which matches the same letters and is a different thing to offer.
    expect(await screen.findByRole("button", { name: /tasks · projects/ })).toBeInTheDocument();
  });

  it("offers a related dataset's columns under the relation's name", async () => {
    const user = userEvent.setup();
    mount(widget({ source: "query", sql: "SELECT title FROM tasks WHERE " }));

    await user.click(sqlBox());
    // `name` belongs to projects, which this statement never names — it is
    // reachable only through the relation in front of it.
    await user.type(sqlBox(), "project.");
    expect(await screen.findByRole("button", { name: /^name/i })).toBeInTheDocument();
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

describe("a statement the server refuses", () => {
  const saveButton = () => screen.getByRole("button", { name: /^save$/i });

  it("cannot be saved", async () => {
    // A statement is checked where a definition is normalized, so saving a
    // refused one takes the whole dashboard with it — and the dialog that
    // could fix it has closed by then.
    const user = userEvent.setup();
    mount(widget({ source: "query", sql: SHIPPED_SQL }));

    await waitFor(() => expect(sqlBox()).toHaveValue(SHIPPED_SQL));
    await user.click(sqlBox());
    await user.type(sqlBox(), " nope");

    await waitFor(() => expect(saveButton()).toBeDisabled());
    expect(onSave).not.toHaveBeenCalled();
  });

  it("says so, rather than showing the last good answer", async () => {
    const user = userEvent.setup();
    mount(widget({ source: "query", sql: SHIPPED_SQL }));

    await screen.findByText("Returns: tasks");
    await user.click(sqlBox());
    await user.type(sqlBox(), " nope");

    await waitFor(() => expect(screen.queryByText("Returns: tasks")).not.toBeInTheDocument());
  });

  it("can be saved once it is corrected", async () => {
    const user = userEvent.setup();
    mount(widget({ source: "query", sql: SHIPPED_SQL }));

    await waitFor(() => expect(sqlBox()).toHaveValue(SHIPPED_SQL));
    await user.click(sqlBox());
    await user.type(sqlBox(), " nope");
    await waitFor(() => expect(saveButton()).toBeDisabled());

    await user.type(sqlBox(), "{backspace}{backspace}{backspace}{backspace}{backspace}");
    await waitFor(() => expect(saveButton()).toBeEnabled());

    await user.click(saveButton());
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        binding: expect.objectContaining({ source: "query", sql: SHIPPED_SQL }),
      })
    );
  });

  it("does not block a widget with no statement at all", async () => {
    // The state a widget is in before anybody points it anywhere. It stores
    // fine, and the canvas draws it as one asking to be configured.
    mount(widget({ source: "query", sql: SHIPPED_SQL }));
    const user = userEvent.setup();

    await waitFor(() => expect(sqlBox()).toHaveValue(SHIPPED_SQL));
    await user.clear(sqlBox());
    await waitFor(() => expect(saveButton()).toBeEnabled());
  });
});
