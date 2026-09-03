import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import {
  buildDocumentSummary,
  buildGuild,
  buildInitiative,
  buildProject,
  buildUser,
} from "@/__tests__/factories";
import { buildQueueSummary } from "@/__tests__/factories/queue.factory";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { queryClient } from "@/lib/queryClient";

import { MyToolsPage } from "./MyToolsPage";

const READER = buildUser({ id: 42 });

const HOME = buildGuild({ id: 1, name: "Ravenloft" });
const AWAY = buildGuild({ id: 2, name: "Barovia" });

const page = (items: unknown[], totalCount = items.length) =>
  HttpResponse.json({
    items,
    total_count: totalCount,
    page: 1,
    page_size: 20,
    has_next: false,
  });

/** Every tool answers through the same envelope, so one shape covers all six. */
function stubMyTools({
  counts = {},
  projects = [],
  documents = [],
  queues = [],
}: {
  counts?: Record<string, number>;
  projects?: unknown[];
  documents?: unknown[];
  queues?: unknown[];
} = {}) {
  server.use(
    http.get("/api/v1/me/tools/counts", () =>
      HttpResponse.json({
        counts: {
          project: 0,
          document: 0,
          queue: 0,
          counter_group: 0,
          calendar: 0,
          dashboard: 0,
          ...counts,
        },
      })
    ),
    http.get("/api/v1/me/projects", () => page(projects)),
    http.get("/api/v1/me/documents", () => page(documents)),
    http.get("/api/v1/me/queues", () => page(queues)),
    http.get("/api/v1/me/counter-groups", () => page([])),
    http.get("/api/v1/me/calendars", () => page([])),
    http.get("/api/v1/me/dashboards", () => page([])),
    guildHttp.get("/initiatives/", () => HttpResponse.json([]))
  );
}

const render = (search?: Record<string, unknown>, guilds = [HOME]) =>
  renderPage(MyToolsPage, {
    auth: { user: READER },
    guilds: { guilds, activeGuildId: HOME.id, activeGuild: HOME },
    initialRoute: "/my-tools",
    routerSearch: search,
  });

describe("MyToolsPage", () => {
  beforeEach(() => {
    queryClient.clear();
  });

  it("offers a tab only for the tools the reader has something of", async () => {
    stubMyTools({
      counts: { project: 3, queue: 1 },
      projects: [buildProject({ name: "Apollo", guild_id: HOME.id })],
    });

    render();

    expect(await screen.findByRole("link", { name: "Projects" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Queues" })).toBeInTheDocument();
    // Nothing in any of these anywhere, so no tab onto an empty table.
    expect(screen.queryByRole("link", { name: "Documents" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Calendars" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Dashboards" })).not.toBeInTheDocument();
  });

  it("says there is nothing to browse when no tool has anything behind it", async () => {
    stubMyTools();

    render();

    expect(await screen.findByText("Nothing to browse yet")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("addresses each row in its own community", async () => {
    stubMyTools({
      counts: { document: 2 },
      documents: [buildDocumentSummary({ id: 5, name: "Campaign notes", guild_id: AWAY.id })],
    });

    render({ tool: "documents" }, [HOME, AWAY]);

    const link = await screen.findByRole("link", { name: "Campaign notes" });
    // The reader is standing in guild 1; the row lives in guild 2 and says so.
    expect(link).toHaveAttribute("href", expect.stringContaining("/c/2/"));
    expect(screen.getByRole("link", { name: "Barovia" })).toBeInTheDocument();
  });

  it("switches the whole view to what the reader made", async () => {
    let lastCreatedByMe: string | null = null;
    stubMyTools({ counts: { queue: 1 }, queues: [buildQueueSummary({ name: "Standup" })] });
    server.use(
      http.get("/api/v1/me/queues", ({ request }) => {
        lastCreatedByMe = new URL(request.url).searchParams.get("created_by_me");
        return page([buildQueueSummary({ name: "Standup" })]);
      })
    );

    render({ tool: "queues" });
    await screen.findByRole("link", { name: "Standup" });
    expect(lastCreatedByMe).toBeNull();

    await userEvent.click(screen.getByRole("radio", { name: "Made by me" }));

    await waitFor(() => expect(lastCreatedByMe).toBe("true"));
    expect(screen.getByRole("radio", { name: "Made by me" })).toHaveAttribute("data-state", "on");
  });

  it("narrows the list to the chosen communities", async () => {
    let lastGuildIds: string[] = [];
    stubMyTools({ counts: { project: 1 } });
    server.use(
      http.get("/api/v1/me/projects", ({ request }) => {
        lastGuildIds = new URL(request.url).searchParams.getAll("guild_ids");
        return page([buildProject({ name: "Apollo", guild_id: AWAY.id })]);
      })
    );

    render({ tool: "projects", communities: String(AWAY.id) }, [HOME, AWAY]);

    await screen.findByRole("link", { name: "Apollo" });
    await waitFor(() => expect(lastGuildIds).toEqual([String(AWAY.id)]));
  });

  it("names each row's initiative, wherever it lives", async () => {
    stubMyTools({
      counts: { project: 1 },
      projects: [buildProject({ name: "Apollo", guild_id: AWAY.id, initiative_id: 9 })],
    });
    server.use(
      guildHttp.get("/initiatives/", ({ params }) =>
        HttpResponse.json(
          Number(params.guildId) === AWAY.id
            ? [buildInitiative({ id: 9, name: "Mists", guild_id: AWAY.id })]
            : []
        )
      )
    );

    render({ tool: "projects" }, [HOME, AWAY]);

    expect(await screen.findByRole("link", { name: "Mists" })).toBeInTheDocument();
  });
});
