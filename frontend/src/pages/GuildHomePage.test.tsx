import { screen, waitFor, within } from "@testing-library/react";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import {
  buildDocumentSummary,
  buildGuild,
  buildInitiative,
  buildProject,
} from "@/__tests__/factories";
import { buildQueueSummary } from "@/__tests__/factories/queue.factory";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";

import { GuildHomePage } from "./GuildHomePage";

const INITIATIVE_ID = 7;

const page = (items: unknown[], totalCount = items.length) =>
  HttpResponse.json({
    items,
    total_count: totalCount,
    page: 1,
    page_size: 20,
    has_next: false,
  });

/**
 * The guild home reads every tool through the same paginated envelope, so one
 * stub shape covers all six. Only the selected tool is actually requested.
 */
function stubTools({
  projects = [],
  documents = [],
  queues = [],
}: {
  projects?: unknown[];
  documents?: unknown[];
  queues?: unknown[];
} = {}) {
  server.use(
    guildHttp.get("/projects/", () => page(projects)),
    guildHttp.get("/documents/", () => page(documents)),
    guildHttp.get("/queues/", () => page(queues)),
    guildHttp.get("/counter-groups/", () => page([])),
    guildHttp.get("/calendars/", () => page([])),
    guildHttp.get("/dashboards/", () => page([]))
  );
}

/** A guild admin sees every initiative, so the rail reflects the initiative's
 *  own tool switches rather than one membership row. */
function stubInitiatives(overrides: Record<string, boolean> = {}) {
  server.use(
    guildHttp.get("/initiatives/", () =>
      HttpResponse.json([buildInitiative({ id: INITIATIVE_ID, name: "Apollo", ...overrides })])
    )
  );
}

const renderHome = (search?: Record<string, unknown>) =>
  renderPage(GuildHomePage, {
    guilds: { activeGuildId: 1, activeGuild: buildGuild({ id: 1, role: "admin" }) },
    routerSearch: search,
  });

describe("GuildHomePage", () => {
  it("lists the whole guild's projects under the projects circle", async () => {
    stubInitiatives();
    stubTools({
      projects: [
        buildProject({ id: 1, name: "Lunar Lander", initiative_id: INITIATIVE_ID }),
        buildProject({ id: 2, name: "Rover Telemetry", initiative_id: INITIATIVE_ID }),
      ],
    });

    renderHome();

    expect(await screen.findByRole("link", { name: "Lunar Lander" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Rover Telemetry" })).toBeInTheDocument();
    // Each row names the initiative it came from, since the table spans them all.
    expect(screen.getAllByRole("link", { name: "Apollo" }).length).toBeGreaterThan(0);
  });

  it("shows a circle only for tools an initiative actually enables", async () => {
    stubInitiatives({ queues_enabled: true });
    stubTools({ projects: [buildProject({ id: 1, name: "Lunar Lander" })] });

    renderHome();

    const rail = await screen.findByRole("navigation", { name: "Guild tools" });
    // The rail waits on the initiative list — until it lands only the core
    // tools show, so assert on the settled state.
    expect(await within(rail).findByRole("link", { name: "Queues" })).toBeInTheDocument();
    expect(within(rail).getByRole("link", { name: "Projects" })).toBeInTheDocument();
    // Calendars are off in the only initiative, so the guild has none to browse.
    expect(within(rail).queryByRole("link", { name: "Calendar" })).not.toBeInTheDocument();
  });

  it("switches the table to the tool named in the address", async () => {
    stubInitiatives({ queues_enabled: true });
    stubTools({
      queues: [
        buildQueueSummary({
          id: 3,
          name: "Launch Window",
          initiative_id: INITIATIVE_ID,
          item_count: 4,
        }),
      ],
    });

    renderHome({ tool: "queues" });

    expect(await screen.findByRole("link", { name: "Launch Window" })).toBeInTheDocument();
    // The third column is the tool's own — queues count their items.
    expect(screen.getByRole("columnheader", { name: /items/i })).toBeInTheDocument();
    expect(screen.getByText("4 items")).toBeInTheDocument();
  });

  it("falls back to a reachable tool when the address names an unknown one", async () => {
    stubInitiatives();
    stubTools({ projects: [buildProject({ id: 1, name: "Lunar Lander" })] });

    renderHome({ tool: "not-a-tool" });

    expect(await screen.findByRole("link", { name: "Lunar Lander" })).toBeInTheDocument();
  });

  it("recovers a page number the tool no longer has", async () => {
    stubInitiatives();
    const asked: string[] = [];
    server.use(
      guildHttp.get("/projects/", ({ request }) => {
        const askedPage = new URL(request.url).searchParams.get("page") ?? "1";
        asked.push(askedPage);
        // 40 projects across two pages of 20 — page 99 exists nowhere.
        return askedPage === "99"
          ? page([], 40)
          : page([buildProject({ id: 1, name: "Lunar Lander" })], 40);
      })
    );

    renderHome({ tool: "projects", page: 99 });

    // The guild still holds projects, so it lands back on a page that has them
    // instead of leaving an empty table over 40 rows.
    expect(await screen.findByRole("link", { name: "Lunar Lander" })).toBeInTheDocument();
    expect(asked).toContain("99");
  });

  it("leaves a page number that is in range alone", async () => {
    stubInitiatives();
    const asked: string[] = [];
    server.use(
      guildHttp.get("/projects/", ({ request }) => {
        asked.push(new URL(request.url).searchParams.get("page") ?? "1");
        return page([buildProject({ id: 21, name: "Second Page Project" })], 40);
      })
    );

    renderHome({ tool: "projects", page: 2 });

    expect(await screen.findByRole("link", { name: "Second Page Project" })).toBeInTheDocument();
    // No spurious reset to page 1 while the first response is still in flight.
    await waitFor(() => expect(asked).toEqual(["2"]));
  });

  it("says so when the selected tool has nothing in the guild", async () => {
    stubInitiatives();
    stubTools({ documents: [] });

    renderHome({ tool: "documents" });

    expect(await screen.findByText("Nothing here yet")).toBeInTheDocument();
  });

  it("keeps documents on the same table shape as projects", async () => {
    stubInitiatives();
    stubTools({
      documents: [
        buildDocumentSummary({ id: 5, title: "Flight Rules", initiative_id: INITIATIVE_ID }),
      ],
    });

    renderHome({ tool: "documents" });

    expect(await screen.findByRole("link", { name: "Flight Rules" })).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("columnheader", { name: /type/i })).toBeInTheDocument()
    );
  });
});
