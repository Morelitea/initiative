/**
 * The shelf every card-grid tool is browsed from, asked once for all of them.
 *
 * Each tool used to carry its own copy of this page, so each would have needed
 * its own copy of these tests. The cases come from the page's own `TOOL_INDEX`:
 * add a tool with an entry and it is covered here the moment it exists.
 *
 * What is tool-specific stays where it belongs — the queue's status select and
 * the wiki's tag picker are tested with their tools, not here.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { buildNotificationPlace } from "@/__tests__/factories";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import i18n from "@/__tests__/helpers/i18n-test";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  type ToolIndexEntry,
  ToolIndexPage,
  toolIndexEntry,
} from "@/components/tools/ToolIndexPage";
import { TOOLS, toolRouteSegment } from "@/lib/tools";
import type { TranslateFn } from "@/types/i18n";

const INITIATIVE_ID = 1;

/** Every tool this page serves, each with what it calls its own strings. */
const CASES = TOOLS.flatMap((tool) => {
  const entry = toolIndexEntry(tool);
  return entry ? [{ tool, entry }] : [];
});

/** The keys come from the table, so the loose signature the page itself uses. */
const translate = i18n.t.bind(i18n) as TranslateFn;

/** One of the tool's own strings, read through the key the table declares. */
const copy = (entry: ToolIndexEntry, key: keyof ToolIndexEntry["text"]) =>
  translate(entry.text[key], { ns: entry.text.ns });

/** A string from the shared toolbar/panel chrome. */
const shared = (key: string) => translate(key, { ns: "common" });

/**
 * Fields a tool's card reads beyond the ones every row has. Written out rather
 * than generated: a card that starts reading a new field should fail here
 * loudly rather than render a blank.
 */
const CARD_FIELDS: Partial<Record<Tool, Record<string, unknown>>> = {
  wiki: { page_count: 0 },
  gallery: { image_count: 0, cover: null, preview: [] },
  queue: { item_count: 0, current_round: 1, is_active: true },
  counter_group: { counter_count: 0 },
};

const row = (tool: Tool, fields: { id: number; name: string; archived_at?: string | null }) => ({
  description: null,
  initiative_id: INITIATIVE_ID,
  guild_id: 1,
  created_by: 1,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  archived_at: null,
  can_unarchive: false,
  my_permission_level: "owner",
  comments_enabled: false,
  comment_count: 0,
  tags: [],
  grants: [],
  ...CARD_FIELDS[tool],
  ...fields,
});

/**
 * Serve the tool's list endpoint, honouring the two things the page can ask
 * for: which archive state, and a search. A tool that searches in the browser
 * simply never sends the second, and narrows the same payload itself.
 */
const stubList = (tool: Tool, rows: ReturnType<typeof row>[]) => {
  const requests: URLSearchParams[] = [];
  server.use(
    guildHttp.get(`/${toolRouteSegment(tool)}/`, ({ request }) => {
      const params = new URL(request.url).searchParams;
      requests.push(params);
      const wantArchived = params.get("archived") === "true";
      const search = (params.get("search") ?? "").toLowerCase();
      const items = rows.filter(
        (item) =>
          Boolean(item.archived_at) === wantArchived &&
          (!search || item.name.toLowerCase().includes(search))
      );
      return HttpResponse.json({
        items,
        total_count: items.length,
        page: 1,
        page_size: 50,
        has_next: false,
      });
    })
  );
  return requests;
};

const renderIndex = (tool: Tool) =>
  renderPage(() => <ToolIndexPage tool={tool} fixedInitiativeId={INITIATIVE_ID} canCreate />);

describe("the tool index page", () => {
  it.each(CASES)("$tool names its own empty shelf", async ({ tool, entry }) => {
    stubList(tool, []);

    renderIndex(tool);

    expect(await screen.findByText(copy(entry, "emptyTitle"))).toBeInTheDocument();
    expect(screen.getByText(copy(entry, "emptyBody"))).toBeInTheDocument();
  });

  it.each(CASES)("$tool reaches its archived rows from the toolbar", async ({ tool }) => {
    const requests = stubList(tool, [
      row(tool, { id: 1, name: "Still in use" }),
      row(tool, { id: 2, name: "Put away", archived_at: "2026-02-01T00:00:00Z" }),
    ]);

    renderIndex(tool);

    expect(await screen.findByText("Still in use")).toBeInTheDocument();
    expect(screen.queryByText("Put away")).not.toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("radio", { name: shared("toolArchiveFilter.archived") })
    );

    expect(await screen.findByText("Put away")).toBeInTheDocument();
    await waitFor(() => expect(requests.at(-1)?.get("archived")).toBe("true"));
  });

  it.each(CASES)("$tool opens its filters from the toolbar", async ({ tool, entry }) => {
    stubList(tool, []);

    renderIndex(tool);
    await screen.findByText(copy(entry, "emptyTitle"));

    const button = screen.getByRole("button", { name: shared("toolbar.filters") });
    expect(button).toHaveAttribute("aria-expanded", "false");

    await userEvent.click(button);

    expect(button).toHaveAttribute("aria-expanded", "true");
  });

  it.each(CASES)("$tool says so when the search matches nothing", async ({ tool, entry }) => {
    stubList(tool, [row(tool, { id: 1, name: "Findable" })]);

    renderIndex(tool);
    expect(await screen.findByText("Findable")).toBeInTheDocument();

    await userEvent.type(
      screen.getByLabelText(i18n.t("filters.searchLabel", { ns: entry.text.ns })),
      "nothing here"
    );

    // Not the empty shelf: the tool has rows, they are just not these.
    expect(await screen.findByText(copy(entry, "noMatches"))).toBeInTheDocument();
    expect(screen.queryByText(copy(entry, "emptyTitle"))).not.toBeInTheDocument();
  });

  it.each(CASES)("$tool is created from the shared dialog", async ({ tool, entry }) => {
    stubList(tool, []);
    let sent: unknown;
    server.use(
      guildHttp.post(`/${toolRouteSegment(tool)}/`, async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(row(tool, { id: 9, name: "Fresh" }));
      })
    );

    renderIndex(tool);
    await userEvent.click(await screen.findByRole("button", { name: copy(entry, "create") }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(copy(entry, "createDescription"))).toBeInTheDocument();
    await userEvent.type(
      within(dialog).getByLabelText(translate("name", { ns: entry.text.ns })),
      "Fresh"
    );
    await userEvent.click(within(dialog).getByRole("button", { name: copy(entry, "create") }));

    await waitFor(() =>
      expect(sent).toMatchObject({ name: "Fresh", initiative_id: INITIATIVE_ID })
    );
  });

  it.each(CASES)("$tool opens a row at its own address", async ({ tool }) => {
    stubList(tool, [row(tool, { id: 7, name: "Openable" })]);

    renderIndex(tool);

    const link = (await screen.findByText("Openable")).closest("a");
    expect(link).toHaveAttribute("href", `/c/1/i/${INITIATIVE_ID}/${toolRouteSegment(tool)}/7`);
  });

  it.each(CASES)("$tool marks the row with something unread", async ({ tool }) => {
    stubList(tool, [
      row(tool, { id: 7, name: "Talked about" }),
      row(tool, { id: 8, name: "Quiet" }),
    ]);
    server.use(
      http.get("/api/v1/notifications/unread", () =>
        HttpResponse.json({ places: [buildNotificationPlace({ tool, resource_id: 7 })] })
      )
    );

    renderIndex(tool);

    await screen.findByText("Quiet");
    const dot = await screen.findByRole("img", { name: translate("guilds:unreadHere") });
    expect(screen.getAllByRole("img", { name: translate("guilds:unreadHere") })).toHaveLength(1);
    expect(dot.parentElement).toHaveTextContent("Talked about");
  });
});
