import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import {
  buildBanner,
  buildDocumentSummary,
  buildGuild,
  buildInitiative,
  buildInitiativeDirectoryEntry,
  buildInitiativeJoinRequest,
  buildProject,
  buildRecentActivityEntry,
} from "@/__tests__/factories";
import { buildQueueSummary } from "@/__tests__/factories/queue.factory";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { queryClient } from "@/lib/queryClient";

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

/** What the community offers to join. Empty by default, as in the shared handlers. */
function stubDirectory(entries: unknown[]) {
  server.use(guildHttp.get("/initiatives/directory", () => HttpResponse.json(entries)));
}

const renderHome = (search?: Record<string, unknown>) =>
  renderPage(GuildHomePage, {
    guilds: { activeGuildId: 1, activeGuild: buildGuild({ id: 1, role: "admin" }) },
    routerSearch: search,
  });

/** The same page seen by a plain member — no create affordance, no admin view
 *  of every initiative. */
const renderHomeAsMember = (search?: Record<string, unknown>) =>
  renderPage(GuildHomePage, {
    guilds: { activeGuildId: 1, activeGuild: buildGuild({ id: 1, role: "member" }) },
    routerSearch: search,
  });

describe("GuildHomePage", () => {
  // One test mounts against the app's own query client (the one the
  // invalidation helpers address); clear it so nothing carries between tests.
  beforeEach(() => {
    queryClient.clear();
  });

  it("heads the page with the community's banner, carrying its own name and description", async () => {
    stubInitiatives();
    stubTools();

    renderPage(GuildHomePage, {
      guilds: {
        activeGuildId: 1,
        activeGuild: buildGuild({
          id: 1,
          role: "admin",
          name: "Ravenloft Chronicle",
          description: "A long campaign in the mists",
          banner: buildBanner({ image_url: "/api/v1/guilds/1/image/abc" }),
        }),
      },
    });

    const heading = await screen.findByRole("heading", { name: "Ravenloft Chronicle" });
    expect(heading).toBeInTheDocument();
    expect(screen.getByText("A long campaign in the mists")).toBeInTheDocument();
  });

  it("uses the banner colour when the community set one instead of artwork", async () => {
    stubInitiatives();
    stubTools();

    const { container } = renderPage(GuildHomePage, {
      guilds: {
        activeGuildId: 1,
        activeGuild: buildGuild({
          id: 1,
          role: "admin",
          banner: buildBanner({ color: "#2a9d8f" }),
        }),
      },
    });

    await screen.findByRole("heading", { level: 1 });
    expect(container.querySelector('[style*="rgb(42, 157, 143)"]')).not.toBeNull();
  });

  it("heads a community with no artwork with its colour, not a plain title", async () => {
    stubInitiatives();
    stubTools();

    const { container } = renderPage(GuildHomePage, {
      guilds: { activeGuildId: 1, activeGuild: buildGuild({ id: 1, role: "admin" }) },
    });

    await screen.findByRole("heading", { level: 1 });
    // Every guild has a banner; this one's is the colour it wears by default.
    expect(container.querySelector('[style*="rgb(37, 99, 235)"]')).not.toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });

  it("says how big the community is and how many are in it right now", async () => {
    stubInitiatives();
    stubTools();

    renderPage(GuildHomePage, {
      guilds: {
        activeGuildId: 1,
        activeGuild: buildGuild({ id: 1, role: "admin", member_count: 11, online_count: 3 }),
      },
    });

    await screen.findByRole("heading", { level: 1 });
    expect(screen.getByText("11 members")).toBeInTheDocument();
    expect(screen.getByText("3 online")).toBeInTheDocument();
  });

  it("says nothing about presence in an empty room", async () => {
    stubInitiatives();
    stubTools();

    renderPage(GuildHomePage, {
      guilds: {
        activeGuildId: 1,
        activeGuild: buildGuild({ id: 1, role: "admin", member_count: 4, online_count: 0 }),
      },
    });

    await screen.findByRole("heading", { level: 1 });
    // "0 online" reads as a verdict on the guild rather than on the moment.
    expect(screen.getByText("4 members")).toBeInTheDocument();
    expect(screen.queryByText(/online/)).not.toBeInTheDocument();
  });

  it("carries the community's own banner layout through to the banner", async () => {
    stubInitiatives();
    stubTools();

    const { container } = renderPage(GuildHomePage, {
      guilds: {
        activeGuildId: 1,
        activeGuild: buildGuild({
          id: 1,
          role: "admin",
          banner: buildBanner({ text_align: "left", fade: "strong" }),
        }),
      },
    });

    await screen.findByRole("heading", { level: 1 });
    expect(container.querySelector("h1")?.parentElement?.className).toContain("text-left");
    // A faded banner is extended and the same amount taken back, so the rail
    // and the table below end up over its tail.
    const banner = container.querySelector<HTMLElement>("div.grid");
    expect(banner?.style.marginBottom).toBe("-224px");
  });

  it("centres the tool circles under a banner that centres its copy", async () => {
    stubInitiatives();
    stubTools();

    renderPage(GuildHomePage, {
      guilds: {
        activeGuildId: 1,
        activeGuild: buildGuild({
          id: 1,
          role: "admin",
          banner: buildBanner({ text_align: "center" }),
        }),
      },
    });

    await screen.findByRole("heading", { level: 1 });
    const rail = screen.getByRole("navigation", { name: /tool/i }).firstElementChild;
    expect(rail?.className).toContain("justify-center");
  });

  it("keeps them against the edge the banner's copy sits on when it is left", async () => {
    stubInitiatives();
    stubTools();

    renderPage(GuildHomePage, {
      guilds: {
        activeGuildId: 1,
        activeGuild: buildGuild({
          id: 1,
          role: "admin",
          banner: buildBanner({ text_align: "left" }),
        }),
      },
    });

    await screen.findByRole("heading", { level: 1 });
    const rail = screen.getByRole("navigation", { name: /tool/i }).firstElementChild;
    expect(rail?.className).not.toContain("justify-center");
  });

  it("lists the whole community's projects under the projects circle", async () => {
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

    const rail = await screen.findByRole("navigation", { name: "Community tools" });
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

  it("asks the server for most-recently-updated first, unasked", async () => {
    stubInitiatives();
    const asked: URL[] = [];
    server.use(
      guildHttp.get("/projects/", ({ request }) => {
        asked.push(new URL(request.url));
        return page([buildProject({ id: 1, name: "Lunar Lander" })]);
      })
    );

    renderHome();

    expect(await screen.findByRole("link", { name: "Lunar Lander" })).toBeInTheDocument();
    expect(asked[0].searchParams.get("sort_by")).toBe("updated_at");
    expect(asked[0].searchParams.get("sort_dir")).toBe("desc");
  });

  it("searches the whole community rather than the page in hand", async () => {
    stubInitiatives();
    const asked: string[] = [];
    server.use(
      guildHttp.get("/projects/", ({ request }) => {
        const search = new URL(request.url).searchParams.get("search");
        asked.push(search ?? "");
        return page(
          search
            ? [buildProject({ id: 2, name: "Rover Telemetry" })]
            : [
                buildProject({ id: 1, name: "Lunar Lander" }),
                buildProject({ id: 2, name: "Rover Telemetry" }),
              ]
        );
      })
    );

    renderHome();
    await screen.findByRole("link", { name: "Lunar Lander" });

    await userEvent.type(screen.getByPlaceholderText("Search by name…"), "rover");

    // The text goes to the server, and the row it does not match leaves — it
    // was never a client-side filter over the twenty rows already fetched.
    await waitFor(() => expect(asked).toContain("rover"));
    await waitFor(() =>
      expect(screen.queryByRole("link", { name: "Lunar Lander" })).not.toBeInTheDocument()
    );
    expect(screen.getByRole("link", { name: "Rover Telemetry" })).toBeInTheDocument();
  });

  it("keeps the search box on screen when the search finds nothing", async () => {
    stubInitiatives();
    server.use(
      guildHttp.get("/projects/", ({ request }) =>
        new URL(request.url).searchParams.get("search")
          ? page([])
          : page([buildProject({ id: 1, name: "Lunar Lander" })])
      )
    );

    renderHome();
    await screen.findByRole("link", { name: "Lunar Lander" });

    await userEvent.type(screen.getByPlaceholderText("Search by name…"), "zzz");

    // Not the "nothing here yet" story, which would take away the only way to
    // unsay the search.
    await waitFor(() =>
      expect(screen.queryByRole("link", { name: "Lunar Lander" })).not.toBeInTheDocument()
    );
    expect(screen.getByPlaceholderText("Search by name…")).toHaveValue("zzz");
    expect(screen.queryByText("Nothing here yet")).not.toBeInTheDocument();
  });

  it("sorts by a column header, and says so in the address", async () => {
    stubInitiatives();
    const asked: URL[] = [];
    server.use(
      guildHttp.get("/projects/", ({ request }) => {
        asked.push(new URL(request.url));
        return page([buildProject({ id: 1, name: "Lunar Lander" })]);
      })
    );

    renderHome();
    await screen.findByRole("link", { name: "Lunar Lander" });

    await userEvent.click(screen.getByRole("button", { name: /^name/i }));

    await waitFor(() => expect(asked.at(-1)?.searchParams.get("sort_by")).toBe("name"));
    expect(asked.at(-1)?.searchParams.get("sort_dir")).toBe("asc");
  });

  it("takes the order from the address, so a sorted table is a link", async () => {
    stubInitiatives();
    const asked: URL[] = [];
    server.use(
      guildHttp.get("/projects/", ({ request }) => {
        asked.push(new URL(request.url));
        return page([buildProject({ id: 1, name: "Lunar Lander" })]);
      })
    );

    renderHome({ sort: "initiative", dir: "desc" });

    expect(await screen.findByRole("link", { name: "Lunar Lander" })).toBeInTheDocument();
    expect(asked[0].searchParams.get("sort_by")).toBe("initiative");
    expect(asked[0].searchParams.get("sort_dir")).toBe("desc");
  });

  it("toggles from the order in the address, not the one it mounted with", async () => {
    stubInitiatives();
    const asked: URL[] = [];
    server.use(
      guildHttp.get("/projects/", ({ request }) => {
        asked.push(new URL(request.url));
        return page([buildProject({ id: 1, name: "Lunar Lander" })]);
      })
    );

    const { router } = renderHome();
    await screen.findByRole("link", { name: "Lunar Lander" });

    // The order changes after the table mounted — the back button landing on
    // one, say. The headers have to follow it, or the next click toggles from
    // where the table came in rather than from what the rows are actually in.
    await router.navigate({ to: "/", search: { sort: "name", dir: "asc" } });
    await waitFor(() => expect(asked.at(-1)?.searchParams.get("sort_by")).toBe("name"));

    await userEvent.click(screen.getByRole("button", { name: /^name/i }));

    // Ascending was showing, so one click means descending.
    await waitFor(() => expect(asked.at(-1)?.searchParams.get("sort_dir")).toBe("desc"));
    expect(asked.at(-1)?.searchParams.get("sort_by")).toBe("name");
  });

  it("drops a half-typed search when the tool changes under it", async () => {
    stubInitiatives({ queues_enabled: true });
    const asked: string[] = [];
    server.use(
      guildHttp.get("/projects/", () => page([buildProject({ id: 1, name: "Lunar Lander" })])),
      guildHttp.get("/queues/", ({ request }) => {
        asked.push(new URL(request.url).searchParams.get("search") ?? "");
        return page([buildQueueSummary({ id: 3, name: "Launch Window" })]);
      })
    );

    const { router } = renderHome();
    await screen.findByRole("link", { name: "Lunar Lander" });

    // Typed, then a tool picked before the search had gone anywhere — the
    // rail's own link carries the tool and nothing else.
    await userEvent.type(screen.getByPlaceholderText("Search by name…"), "rover");
    await router.navigate({ to: "/", search: { tool: "queues" } });

    expect(await screen.findByRole("link", { name: "Launch Window" })).toBeInTheDocument();
    // The new tool is not narrowed by what was meant for the last one, and the
    // box that text was typed into is empty.
    await waitFor(() => expect(asked.length).toBeGreaterThan(0));
    expect(asked.every((search) => search === "")).toBe(true);
    expect(screen.getByPlaceholderText("Search by name…")).toHaveValue("");
  });

  it("says so when the selected tool has nothing in the community", async () => {
    stubInitiatives();
    stubTools({ documents: [] });

    renderHome({ tool: "documents" });

    expect(await screen.findByText("Nothing here yet")).toBeInTheDocument();
  });

  it("shows the community's latest comments under the table", async () => {
    stubInitiatives();
    stubTools({ projects: [buildProject({ id: 1, name: "Lunar Lander" })] });
    server.use(
      guildHttp.get("/comments/recent", () =>
        HttpResponse.json([
          buildRecentActivityEntry({
            comment_id: 11,
            content: "Ready for the review",
            task_id: 4,
            task_title: "Fuel check",
            project_id: 1,
            project_name: "Lunar Lander",
            initiative_id: 5,
          }),
        ])
      )
    );

    renderHome();

    expect(await screen.findByText("Ready for the review")).toBeInTheDocument();
    // The feed names where the comment was left and links to it.
    expect(screen.getByText("on Fuel check in Lunar Lander")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Ready for the review/ })).toHaveAttribute(
      "href",
      "/c/1/i/5/projects/1/tasks/4"
    );
  });

  it("links a comment left on a tool entity to that entity", async () => {
    stubInitiatives({ queues_enabled: true });
    stubTools({ queues: [] });
    server.use(
      guildHttp.get("/comments/recent", () =>
        HttpResponse.json([
          buildRecentActivityEntry({
            comment_id: 12,
            content: "Order looks wrong",
            entity_type: "queue",
            entity_id: 8,
            entity_name: "Combat Order",
            initiative_id: 5,
          }),
        ])
      )
    );

    renderHome({ tool: "queues" });

    expect(await screen.findByText("on Combat Order")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Order looks wrong/ })).toHaveAttribute(
      "href",
      "/c/1/i/5/queues/8"
    );
  });

  it("addresses a community-level calendar's comment at the community route", async () => {
    stubInitiatives({ calendars_enabled: true });
    stubTools();
    server.use(
      guildHttp.get("/comments/recent", () =>
        HttpResponse.json([
          buildRecentActivityEntry({
            comment_id: 13,
            content: "Moving this to Thursday",
            entity_type: "calendar",
            entity_id: 3,
            entity_name: "Club Nights",
            initiative_id: null,
          }),
        ])
      )
    );

    renderHome();

    expect(await screen.findByText("on Club Nights")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Moving this to Thursday/ })).toHaveAttribute(
      "href",
      "/c/1/calendars/3"
    );
  });

  it("keeps the comment feed while the rail switches tools", async () => {
    stubInitiatives({ queues_enabled: true });
    stubTools({ queues: [] });
    server.use(
      guildHttp.get("/comments/recent", () =>
        HttpResponse.json([buildRecentActivityEntry({ content: "Still here" })])
      )
    );

    // Queues are empty, so the table is replaced by its empty state — the
    // guild-wide feed is not.
    renderHome({ tool: "queues" });

    expect(await screen.findByText("Nothing here yet")).toBeInTheDocument();
    expect(screen.getByText("Still here")).toBeInTheDocument();
  });

  it("says so when the community has no comments yet", async () => {
    stubInitiatives();
    stubTools({ projects: [buildProject({ id: 1, name: "Lunar Lander" })] });

    renderHome();

    expect(await screen.findByText("No comments yet")).toBeInTheDocument();
  });

  it("lists the community's initiatives under the table, grouped by where you stand", async () => {
    stubInitiatives();
    stubTools({ projects: [buildProject({ id: 1, name: "Lunar Lander" })] });
    stubDirectory([
      buildInitiativeDirectoryEntry({ id: INITIATIVE_ID, name: "Apollo", is_member: true }),
      buildInitiativeDirectoryEntry({ id: 9, name: "Nebula", join_policy: "open" }),
    ]);

    renderHome();

    expect(await screen.findByRole("heading", { name: "Initiatives" })).toBeInTheDocument();
    const mine = (await screen.findByRole("heading", { name: "Your initiatives" }))
      .parentElement as HTMLElement;
    const joinable = screen.getByRole("heading", { name: "Open to join" })
      .parentElement as HTMLElement;
    expect(within(mine).getByRole("link", { name: "Apollo" })).toBeInTheDocument();
    expect(within(joinable).getByRole("button", { name: "Join" })).toBeInTheDocument();
  });

  it("folds the whole initiatives section away from its heading", async () => {
    stubInitiatives();
    stubTools({ projects: [buildProject({ id: 1, name: "Lunar Lander" })] });
    stubDirectory([buildInitiativeDirectoryEntry({ id: 9, name: "Nebula", join_policy: "open" })]);

    renderHome();

    await userEvent.click(await screen.findByRole("button", { name: /Initiatives/ }));

    await waitFor(() => expect(screen.queryByText("Nebula")).not.toBeInTheDocument());
    // The rest of the page is untouched by the fold.
    expect(screen.getByRole("link", { name: "Lunar Lander" })).toBeInTheDocument();
  });

  it("offers a community admin the create dialog from the section header", async () => {
    stubInitiatives();
    stubTools({ projects: [buildProject({ id: 1, name: "Lunar Lander" })] });
    stubDirectory([buildInitiativeDirectoryEntry({ id: 9, name: "Nebula", join_policy: "open" })]);

    renderHome();

    await userEvent.click(await screen.findByRole("button", { name: /New initiative/i }));

    expect(await screen.findByRole("dialog")).toHaveTextContent("Create initiative");
  });

  it("keeps creating out of a member's hands", async () => {
    stubInitiatives();
    stubTools({ projects: [buildProject({ id: 1, name: "Lunar Lander" })] });
    stubDirectory([buildInitiativeDirectoryEntry({ id: 9, name: "Nebula", join_policy: "open" })]);

    renderHomeAsMember();

    expect(await screen.findByRole("heading", { name: "Initiatives" })).toBeInTheDocument();
    // The backend refuses it either way; the affordance doesn't pretend.
    expect(screen.queryByRole("button", { name: /New initiative/i })).not.toBeInTheDocument();
  });

  it("opens the create dialog for the ?create=true deep link", async () => {
    stubInitiatives();
    stubTools({ projects: [buildProject({ id: 1, name: "Lunar Lander" })] });

    renderHome({ create: "true" });

    // The sidebar's "Add initiative" and the retired /i list route both land here.
    expect(await screen.findByRole("dialog")).toHaveTextContent("Create initiative");
  });

  it("re-reads the community once the reader joins, so the card flips to joined", async () => {
    stubInitiatives();
    stubTools({ projects: [buildProject({ id: 1, name: "Lunar Lander" })] });

    // The membership row is what the directory reports back on, so the second
    // read — the one the join's invalidation forces — answers differently.
    let joined = false;
    server.use(
      guildHttp.get("/initiatives/directory", () =>
        HttpResponse.json([
          buildInitiativeDirectoryEntry({
            id: 9,
            name: "Nebula",
            join_policy: "open",
            is_member: joined,
          }),
        ])
      ),
      guildHttp.post("/initiatives/:id/join", () => {
        joined = true;
        return HttpResponse.json(buildInitiative({ id: 9, name: "Nebula", join_policy: "open" }));
      })
    );

    // The invalidation helpers address the app's own query client, so this
    // flow is only observable when the page is mounted against it.
    renderPage(GuildHomePage, {
      guilds: { activeGuildId: 1, activeGuild: buildGuild({ id: 1, role: "admin" }) },
      queryClient,
    });

    await userEvent.click(await screen.findByRole("button", { name: "Join" }));

    // Once you're in, the card's title leads there and the Join is spent.
    expect(await screen.findByRole("link", { name: "Nebula" })).toHaveAttribute("href", "/c/1/i/9");
    expect(screen.queryByRole("button", { name: "Join" })).not.toBeInTheDocument();
  });

  it("re-reads the community once the reader knocks, so the card flips to requested", async () => {
    stubInitiatives();
    stubTools({ projects: [buildProject({ id: 1, name: "Lunar Lander" })] });

    // Asking changes nothing about what the reader can see — only the card's
    // own state — so the directory is what has to answer differently.
    let requested = false;
    server.use(
      guildHttp.get("/initiatives/directory", () =>
        HttpResponse.json([
          buildInitiativeDirectoryEntry({
            id: 9,
            name: "Vanguard",
            join_policy: "request",
            has_pending_request: requested,
          }),
        ])
      ),
      guildHttp.post("/initiatives/:id/join-requests", () => {
        requested = true;
        return HttpResponse.json(buildInitiativeJoinRequest({ initiative_id: 9 }), {
          status: 201,
        });
      })
    );

    // The invalidation helpers address the app's own query client, so this
    // flow is only observable when the page is mounted against it.
    renderPage(GuildHomePage, {
      guilds: { activeGuildId: 1, activeGuild: buildGuild({ id: 1, role: "member" }) },
      queryClient,
    });

    await userEvent.click(await screen.findByRole("button", { name: "Request to join" }));
    await userEvent.click(await screen.findByRole("button", { name: "Send request" }));

    // Waiting on a manager is a state, not an action.
    expect(await screen.findByText("Requested")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Request to join" })).not.toBeInTheDocument();
  });

  it("tells a member with no initiatives how to get into one", async () => {
    server.use(guildHttp.get("/initiatives/", () => HttpResponse.json([])));
    stubTools();
    stubDirectory([buildInitiativeDirectoryEntry({ id: 9, name: "Nebula", join_policy: "open" })]);

    renderHomeAsMember();

    expect(await screen.findByText(/You haven’t joined any initiatives yet/)).toBeInTheDocument();
    // The directory is the way in, so it takes the page over from the rail.
    expect(screen.getByRole("button", { name: "Join" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Community tools" })).not.toBeInTheDocument();
  });

  it("does not call a failed lookup an empty membership", async () => {
    server.use(guildHttp.get("/initiatives/", () => new HttpResponse(null, { status: 500 })));
    stubTools();
    stubDirectory([]);

    renderHomeAsMember();

    // A request that never answered is not proof the reader is in nothing —
    // saying so would be a confident lie about their own access.
    expect(await screen.findByRole("navigation", { name: "Community tools" })).toBeInTheDocument();
    expect(screen.queryByText(/You haven’t joined any initiatives yet/)).not.toBeInTheDocument();
  });

  it("does not call a failed directory an empty one", async () => {
    server.use(
      guildHttp.get("/initiatives/", () => HttpResponse.json([])),
      guildHttp.get("/initiatives/directory", () => new HttpResponse(null, { status: 500 }))
    );
    stubTools();

    renderHomeAsMember();

    // Being in nothing is established; having nothing to join is not, so the
    // page says the list failed rather than inventing an empty guild.
    expect(await screen.findByText(/You haven’t joined any initiatives yet/)).toBeInTheDocument();
    expect(
      await screen.findByText(/couldn't load what this community has on offer/i)
    ).toBeInTheDocument();
    expect(screen.queryByText("Nothing to join yet")).not.toBeInTheDocument();
  });

  it("stays honest when the community has nothing on offer either", async () => {
    server.use(guildHttp.get("/initiatives/", () => HttpResponse.json([])));
    stubTools();
    stubDirectory([]);

    renderHomeAsMember();

    expect(await screen.findByText("Nothing to join yet")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Join" })).not.toBeInTheDocument();
    // A member has no way to make one, so nothing offers it.
    expect(screen.queryByRole("button", { name: /Create initiative/i })).not.toBeInTheDocument();
  });

  it("offers an admin of an empty community the first initiative", async () => {
    server.use(guildHttp.get("/initiatives/", () => HttpResponse.json([])));
    stubTools();
    stubDirectory([]);

    renderHome();

    await userEvent.click(await screen.findByRole("button", { name: /Create initiative/i }));

    expect(await screen.findByRole("dialog")).toHaveTextContent("Create initiative");
  });

  it("keeps documents on the same table shape as projects", async () => {
    stubInitiatives();
    stubTools({
      documents: [
        buildDocumentSummary({ id: 5, name: "Flight Rules", initiative_id: INITIATIVE_ID }),
      ],
    });

    renderHome({ tool: "documents" });

    expect(await screen.findByRole("link", { name: "Flight Rules" })).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("columnheader", { name: /type/i })).toBeInTheDocument()
    );
  });
});
