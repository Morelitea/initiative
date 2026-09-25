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
  buildInitiativeMember,
  buildProject,
  buildRecentActivityEntry,
  buildUser,
  initiativeCan,
} from "@/__tests__/factories";
import { buildQueueSummary } from "@/__tests__/factories/queue.factory";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { BannerTextAlign } from "@/api/generated/initiativeAPI.schemas";
import { queryClient } from "@/lib/queryClient";
import { isToolEnabled, TOOLS } from "@/lib/tools";

import { GuildHomePage } from "./GuildHomePage";

const INITIATIVE_ID = 7;

/** Whoever is reading the page. Pinned so the stubbed listing can carry their
 *  membership row — which is what the endpoint returns, guild admin or not. */
const READER = buildUser({ id: 42 });

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

/** The listing is the reader's own memberships, guild admin or not, so the
 *  stub carries their row, and may view every tool the initiative has on. */
function stubInitiatives(overrides: Record<string, boolean> = {}) {
  const initiative = buildInitiative({
    id: INITIATIVE_ID,
    name: "Apollo",
    members: [buildInitiativeMember({ user: { ...READER } })],
    ...overrides,
  });
  initiative.can = initiativeCan({ view: TOOLS.filter((tool) => isToolEnabled(tool, initiative)) });
  server.use(guildHttp.get("/initiatives/", () => HttpResponse.json([initiative])));
}

/** What the community offers to join. Empty by default, as in the shared handlers. */
function stubDirectory(entries: unknown[]) {
  server.use(guildHttp.get("/initiatives/directory", () => HttpResponse.json(entries)));
}

/** One card on offer whose own state flips once the reader has acted on it —
 *  which is what re-reading the directory has to surface. */
function stubFlippingDirectory(
  entry: Parameters<typeof buildInitiativeDirectoryEntry>[0],
  flips: "is_member" | "has_pending_request"
) {
  const acted = { yet: false };
  server.use(
    guildHttp.get("/initiatives/directory", () =>
      HttpResponse.json([buildInitiativeDirectoryEntry({ ...entry, [flips]: acted.yet })])
    )
  );
  return acted;
}

/** A community with nothing in it: no initiatives, no tools, and whatever —
 *  usually nothing — it has on offer to join. */
function stubEmptyCommunity(directory: unknown[] = []) {
  server.use(guildHttp.get("/initiatives/", () => HttpResponse.json([])));
  stubTools();
  stubDirectory(directory);
}

/** The ordinary background: one initiative the reader is in, holding one
 *  project, so the table below the rail has a row. */
function stubOneProject() {
  stubInitiatives();
  stubTools({ projects: [buildProject({ id: 1, name: "Lunar Lander" })] });
}

/** Answers the projects listing, recording every request the table made. */
function watchProjects(respond: (url: URL) => Response = () => page([LANDER()])) {
  const asked: URL[] = [];
  server.use(
    guildHttp.get("/projects/", ({ request }) => {
      const url = new URL(request.url);
      asked.push(url);
      return respond(url);
    })
  );
  return asked;
}

const LANDER = () => buildProject({ id: 1, name: "Lunar Lander" });
const NEBULA = () => buildInitiativeDirectoryEntry({ id: 9, name: "Nebula", join_policy: "open" });
const pageOf = (url: URL) => url.searchParams.get("page") ?? "1";
const sought = (asked: URL[], key: string) => asked.at(-1)?.searchParams.get(key);

/** One case of the feed: what the community holds, what was said, and where
 *  the entry has to lead. */
type FeedCase = [
  label: string,
  community: {
    initiative?: Record<string, boolean>;
    tools?: Parameters<typeof stubTools>[0];
    search?: Record<string, unknown>;
  },
  entry: NonNullable<Parameters<typeof buildRecentActivityEntry>[0]>,
  says: string,
  href: string,
];

/** One comment in the community's feed, wherever it was left. */
function stubRecentComment(overrides: Parameters<typeof buildRecentActivityEntry>[0]) {
  server.use(
    guildHttp.get("/comments/recent", () =>
      HttpResponse.json([buildRecentActivityEntry(overrides)])
    )
  );
}

const renderHome = (search?: Record<string, unknown>) =>
  renderPage(GuildHomePage, {
    auth: { user: READER },
    guilds: { activeGuildId: 1, activeGuild: buildGuild({ id: 1, role: "admin" }) },
    routerSearch: search,
  });

/** The same page over a community that carries something particular: the
 *  banner cases turn on what the guild *is*, not on what is in it. */
const renderHomeFor = (guild: Parameters<typeof buildGuild>[0]) =>
  renderPage(GuildHomePage, {
    guilds: { activeGuildId: 1, activeGuild: buildGuild({ id: 1, role: "admin", ...guild }) },
  });

/** Mounted against the app's own query client — the one the invalidation
 *  helpers address, so a flow that turns on a refetch is observable at all. */
const renderHomeLive = (role: "admin" | "member") =>
  renderPage(GuildHomePage, {
    guilds: { activeGuildId: 1, activeGuild: buildGuild({ id: 1, role }) },
    queryClient,
  });

/** The same page seen by a plain member — no create affordance. */
const renderHomeAsMember = (search?: Record<string, unknown>) =>
  renderPage(GuildHomePage, {
    auth: { user: READER },
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

    renderHomeFor({
      name: "Ravenloft Chronicle",
      description: "A long campaign in the mists",
      banner: buildBanner({ image_url: "/api/v1/communities/1/image/abc" }),
    });

    const heading = await screen.findByRole("heading", { name: "Ravenloft Chronicle" });
    expect(heading).toBeInTheDocument();
    expect(screen.getByText("A long campaign in the mists")).toBeInTheDocument();
  });

  // Every guild has a banner, so a community that set no artwork is headed by
  // the colour it wears rather than by a plain title.
  it.each([
    [
      "the colour the community set instead of artwork",
      buildBanner({ color: "#2a9d8f" }),
      "rgb(42, 157, 143)",
    ],
    ["the colour it wears by default", buildBanner(), "rgb(37, 99, 235)"],
  ])("heads a community with no artwork with %s", async (_label, banner, colour) => {
    stubInitiatives();
    stubTools();

    const { container } = renderHomeFor({ banner });

    await screen.findByRole("heading", { level: 1 });
    expect(container.querySelector(`[style*="${colour}"]`)).not.toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });

  // "0 online" reads as a verdict on the guild rather than on the moment, so an
  // empty room says nothing about presence at all.
  it.each([
    ["says how many are in it right now", 11, 3, "11 members", "3 online"],
    ["says nothing about presence in an empty room", 4, 0, "4 members", null],
  ])(
    "says how big the community is, and %s",
    async (_label, member_count, online_count, members, online) => {
      stubInitiatives();
      stubTools();

      renderHomeFor({ member_count, online_count });

      await screen.findByRole("heading", { level: 1 });
      expect(screen.getByText(members)).toBeInTheDocument();
      if (online) {
        expect(screen.getByText(online)).toBeInTheDocument();
      } else {
        expect(screen.queryByText(/online/)).not.toBeInTheDocument();
      }
    }
  );

  it("carries the community's own banner layout through to the banner", async () => {
    stubInitiatives();
    stubTools();

    const { container } = renderHomeFor({
      banner: buildBanner({ text_align: "left", fade: "strong" }),
    });

    await screen.findByRole("heading", { level: 1 });
    expect(container.querySelector("h1")?.parentElement?.className).toContain("text-left");
    // A faded banner is extended and the same amount taken back, so the rail
    // and the table below end up over its tail.
    const banner = container.querySelector<HTMLElement>("div.grid");
    expect(banner?.style.marginBottom).toBe("-224px");
  });

  // The tool circles sit under the banner's copy, so they follow the edge it
  // was aligned to rather than a fixed one of their own.
  it.each<[string, BannerTextAlign, boolean]>([
    ["centres the tool circles under a banner that centres its copy", "center", true],
    ["keeps them against the edge the banner's copy sits on when it is left", "left", false],
  ])("%s", async (_label, text_align, centred) => {
    stubInitiatives();
    stubTools();

    renderHomeFor({ banner: buildBanner({ text_align }) });

    await screen.findByRole("heading", { level: 1 });
    const rail = screen.getByRole("navigation", { name: /tool/i }).firstElementChild;
    if (centred) {
      expect(rail?.className).toContain("justify-center");
    } else {
      expect(rail?.className).not.toContain("justify-center");
    }
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

  // The rail shows only what the guild's initiatives actually turned on, and
  // projects are a tool like any other now — so an initiative that is only
  // documents has no Projects circle to offer.
  it.each([
    [
      "Queues, and none for the calendars it left off",
      { queues_enabled: true },
      ["Queues", "Projects"],
      ["Calendar"],
    ],
    [
      "Documents, and none for the projects it turned off",
      { projects_enabled: false },
      ["Documents"],
      ["Projects"],
    ],
  ])("shows a circle for %s", async (_label, initiative, shown, hidden) => {
    stubInitiatives(initiative);
    stubTools({ projects: [LANDER()] });

    renderHome();

    const rail = await screen.findByRole("navigation", { name: "Community tools" });
    // The rail waits on the initiative list — until it lands only the core
    // tools show, so assert on the settled state.
    expect(await within(rail).findByRole("link", { name: shown[0] })).toBeInTheDocument();
    for (const name of shown.slice(1)) {
      expect(within(rail).getByRole("link", { name })).toBeInTheDocument();
    }
    for (const name of hidden) {
      expect(within(rail).queryByRole("link", { name })).not.toBeInTheDocument();
    }
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
    stubOneProject();

    renderHome({ tool: "not-a-tool" });

    expect(await screen.findByRole("link", { name: "Lunar Lander" })).toBeInTheDocument();
  });

  it("recovers a page number the tool no longer has", async () => {
    stubInitiatives();
    // 40 projects across two pages of 20 — page 99 exists nowhere.
    const asked = watchProjects((url) =>
      pageOf(url) === "99" ? page([], 40) : page([LANDER()], 40)
    );

    renderHome({ tool: "projects", page: 99 });

    // The guild still holds projects, so it lands back on a page that has them
    // instead of leaving an empty table over 40 rows.
    expect(await screen.findByRole("link", { name: "Lunar Lander" })).toBeInTheDocument();
    expect(asked.map(pageOf)).toContain("99");
  });

  it("leaves a page number that is in range alone", async () => {
    stubInitiatives();
    const asked = watchProjects(() =>
      page([buildProject({ id: 21, name: "Second Page Project" })], 40)
    );

    renderHome({ tool: "projects", page: 2 });

    expect(await screen.findByRole("link", { name: "Second Page Project" })).toBeInTheDocument();
    // No spurious reset to page 1 while the first response is still in flight.
    await waitFor(() => expect(asked.map(pageOf)).toEqual(["2"]));
  });

  it("asks the server for most-recently-updated first, unasked", async () => {
    stubInitiatives();
    const asked = watchProjects();

    renderHome();

    expect(await screen.findByRole("link", { name: "Lunar Lander" })).toBeInTheDocument();
    expect(sought(asked, "sort_by")).toBe("updated_at");
    expect(sought(asked, "sort_dir")).toBe("desc");
  });

  it("searches the whole community rather than the page in hand", async () => {
    stubInitiatives();
    const asked = watchProjects((url) =>
      page(
        url.searchParams.get("search")
          ? [buildProject({ id: 2, name: "Rover Telemetry" })]
          : [LANDER(), buildProject({ id: 2, name: "Rover Telemetry" })]
      )
    );

    renderHome();
    await screen.findByRole("link", { name: "Lunar Lander" });

    await userEvent.type(screen.getByPlaceholderText("Search by name…"), "rover");

    // The text goes to the server, and the row it does not match leaves — it
    // was never a client-side filter over the twenty rows already fetched.
    await waitFor(() =>
      expect(asked.map((url) => url.searchParams.get("search"))).toContain("rover")
    );
    await waitFor(() =>
      expect(screen.queryByRole("link", { name: "Lunar Lander" })).not.toBeInTheDocument()
    );
    expect(screen.getByRole("link", { name: "Rover Telemetry" })).toBeInTheDocument();
  });

  it("keeps the search box on screen when the search finds nothing", async () => {
    stubInitiatives();
    watchProjects((url) => (url.searchParams.get("search") ? page([]) : page([LANDER()])));

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
    const asked = watchProjects();

    renderHome();
    await screen.findByRole("link", { name: "Lunar Lander" });

    await userEvent.click(screen.getByRole("button", { name: /^name/i }));

    await waitFor(() => expect(sought(asked, "sort_by")).toBe("name"));
    expect(sought(asked, "sort_dir")).toBe("asc");
  });

  it("takes the order from the address, so a sorted table is a link", async () => {
    stubInitiatives();
    const asked = watchProjects();

    renderHome({ sort: "initiative", dir: "desc" });

    expect(await screen.findByRole("link", { name: "Lunar Lander" })).toBeInTheDocument();
    expect(sought(asked, "sort_by")).toBe("initiative");
    expect(sought(asked, "sort_dir")).toBe("desc");
  });

  it("toggles from the order in the address, not the one it mounted with", async () => {
    stubInitiatives();
    const asked = watchProjects();

    const { router } = renderHome();
    await screen.findByRole("link", { name: "Lunar Lander" });

    // The order changes after the table mounted — the back button landing on
    // one, say. The headers have to follow it, or the next click toggles from
    // where the table came in rather than from what the rows are actually in.
    await router.navigate({ href: "/?sort=name&dir=asc" });
    await waitFor(() => expect(sought(asked, "sort_by")).toBe("name"));

    await userEvent.click(screen.getByRole("button", { name: /^name/i }));

    // Ascending was showing, so one click means descending.
    await waitFor(() => expect(sought(asked, "sort_dir")).toBe("desc"));
    expect(sought(asked, "sort_by")).toBe("name");
  });

  it("drops a half-typed search when the tool changes under it", async () => {
    stubInitiatives({ queues_enabled: true });
    const asked: string[] = [];
    server.use(
      guildHttp.get("/projects/", () => page([LANDER()])),
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
    await router.navigate({ href: "/?tool=queues" });

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

  // The feed under the table is the whole community's. Each entry names where
  // the comment was left and leads straight back to it, on whichever surface
  // that was — including one the community itself holds rather than an
  // initiative.
  it.each<FeedCase>([
    [
      "the community's latest comment on a task, to the task inside its project",
      { tools: { projects: [LANDER()] } },
      {
        comment_id: 11,
        content: "Ready for the review",
        task_id: 4,
        task_title: "Fuel check",
        project_id: 1,
        project_name: "Lunar Lander",
        initiative_id: 5,
      },
      "on Fuel check in Lunar Lander",
      "/c/1/i/5/projects/1/tasks/4",
    ],
    [
      "a comment left on a tool entity, to that entity",
      { initiative: { queues_enabled: true }, tools: { queues: [] }, search: { tool: "queues" } },
      {
        comment_id: 12,
        content: "Order looks wrong",
        entity_type: "queue",
        entity_id: 8,
        entity_name: "Combat Order",
        initiative_id: 5,
      },
      "on Combat Order",
      "/c/1/i/5/queues/8",
    ],
    [
      "a community-level calendar's comment, at the community route",
      { initiative: { calendars_enabled: true } },
      {
        comment_id: 13,
        content: "Moving this to Thursday",
        entity_type: "calendar",
        entity_id: 3,
        entity_name: "Club Nights",
        initiative_id: null,
      },
      "on Club Nights",
      "/c/1/calendars/3",
    ],
  ])("links %s", async (_label, { initiative = {}, tools = {}, search }, entry, says, href) => {
    stubInitiatives(initiative);
    stubTools(tools);
    stubRecentComment(entry);

    renderHome(search);

    expect(await screen.findByText(says)).toBeInTheDocument();
    expect(screen.getByText(String(entry.content))).toBeInTheDocument();
    expect(screen.getByRole("link", { name: new RegExp(String(entry.content)) })).toHaveAttribute(
      "href",
      href
    );
  });

  it("opens an app's settings from the address, where the reader answers what it asked", async () => {
    stubInitiatives();
    stubTools();
    server.use(
      guildHttp.get("/apps/3", () =>
        HttpResponse.json({
          id: 3,
          name: "Auto",
          definition: {},
          enabled: true,
          connections: [],
          consents: [
            {
              id: 41,
              purpose: "node-1",
              label: "Comment on the linked issue",
              initiative_id: null,
              requested_access: "read",
              granted_access: null,
              status: "pending",
              requested_at: "2026-09-24T00:00:00Z",
              granted_at: null,
              revoked_at: null,
            },
          ],
        })
      )
    );

    renderHomeAsMember({ app: 3 });

    expect(await screen.findByText("Auto: “Comment on the linked issue”")).toBeInTheDocument();
    expect(screen.getByText("Waiting for you")).toBeInTheDocument();
  });

  it("keeps the comment feed while the rail switches tools", async () => {
    stubInitiatives({ queues_enabled: true });
    stubTools({ queues: [] });
    stubRecentComment({ content: "Still here" });

    // Queues are empty, so the table is replaced by its empty state — the
    // guild-wide feed is not.
    renderHome({ tool: "queues" });

    expect(await screen.findByText("Nothing here yet")).toBeInTheDocument();
    expect(screen.getByText("Still here")).toBeInTheDocument();
  });

  it("says so when the community has no comments yet", async () => {
    stubOneProject();

    renderHome();

    expect(await screen.findByText("No comments yet")).toBeInTheDocument();
  });

  it("lists the community's initiatives under the table, grouped by where you stand", async () => {
    stubOneProject();
    stubDirectory([
      buildInitiativeDirectoryEntry({ id: INITIATIVE_ID, name: "Apollo", is_member: true }),
      NEBULA(),
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
    stubOneProject();
    stubDirectory([NEBULA()]);

    renderHome();

    await userEvent.click(await screen.findByRole("button", { name: /Initiatives/ }));

    await waitFor(() => expect(screen.queryByText("Nebula")).not.toBeInTheDocument());
    // The rest of the page is untouched by the fold.
    expect(screen.getByRole("link", { name: "Lunar Lander" })).toBeInTheDocument();
  });

  it("offers a community admin the create dialog from the section header", async () => {
    stubOneProject();
    stubDirectory([NEBULA()]);

    renderHome();

    await userEvent.click(await screen.findByRole("button", { name: /New initiative/i }));

    // The wizard opens on its first question, not on a form of everything.
    expect(await screen.findByRole("dialog")).toHaveTextContent("What is it called?");
  });

  it("keeps creating out of a member's hands", async () => {
    stubOneProject();
    stubDirectory([NEBULA()]);

    renderHomeAsMember();

    expect(await screen.findByRole("heading", { name: "Initiatives" })).toBeInTheDocument();
    // The backend refuses it either way; the affordance doesn't pretend.
    expect(screen.queryByRole("button", { name: /New initiative/i })).not.toBeInTheDocument();
  });

  it("opens the create dialog for the ?create=true deep link", async () => {
    stubOneProject();

    renderHome({ create: "true" });

    // The sidebar's "Add initiative" and the retired /i list route both land here.
    // The wizard opens on its first question, not on a form of everything.
    expect(await screen.findByRole("dialog")).toHaveTextContent("What is it called?");
  });

  it("re-reads the community once the reader joins, so the card flips to joined", async () => {
    stubOneProject();

    // The membership row is what the directory reports back on, so the second
    // read — the one the join's invalidation forces — answers differently.
    const acted = stubFlippingDirectory(
      { id: 9, name: "Nebula", join_policy: "open" },
      "is_member"
    );
    server.use(
      guildHttp.post("/initiatives/:id/join", () => {
        acted.yet = true;
        return HttpResponse.json(buildInitiative({ id: 9, name: "Nebula", join_policy: "open" }));
      })
    );

    renderHomeLive("admin");

    await userEvent.click(await screen.findByRole("button", { name: "Join" }));

    // Once you're in, the card's title leads there and the Join is spent.
    expect(await screen.findByRole("link", { name: "Nebula" })).toHaveAttribute("href", "/c/1/i/9");
    expect(screen.queryByRole("button", { name: "Join" })).not.toBeInTheDocument();
  });

  it("re-reads the community once the reader knocks, so the card flips to requested", async () => {
    stubOneProject();

    // Asking changes nothing about what the reader can see — only the card's
    // own state — so the directory is what has to answer differently.
    const acted = stubFlippingDirectory(
      { id: 9, name: "Vanguard", join_policy: "request" },
      "has_pending_request"
    );
    server.use(
      guildHttp.post("/initiatives/:id/join-requests", () => {
        acted.yet = true;
        return HttpResponse.json(buildInitiativeJoinRequest({ initiative_id: 9 }), { status: 201 });
      })
    );

    renderHomeLive("member");

    await userEvent.click(await screen.findByRole("button", { name: "Request to join" }));
    await userEvent.click(await screen.findByRole("button", { name: "Send request" }));

    // Waiting on a manager is a state, not an action.
    expect(await screen.findByText("Requested")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Request to join" })).not.toBeInTheDocument();
  });

  it("tells a member with no initiatives how to get into one", async () => {
    stubEmptyCommunity([NEBULA()]);

    renderHomeAsMember();

    expect(await screen.findByText(/You haven’t joined any initiatives yet/)).toBeInTheDocument();
    // The directory is the way in, so it takes the page over from the rail.
    expect(screen.getByRole("button", { name: "Join" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Community tools" })).not.toBeInTheDocument();
  });

  it("does not call a failed lookup an empty membership", async () => {
    stubEmptyCommunity();
    server.use(guildHttp.get("/initiatives/", () => new HttpResponse(null, { status: 500 })));

    renderHomeAsMember();

    // A request that never answered is not proof the reader is in nothing —
    // saying so would be a confident lie about their own access.
    expect(await screen.findByRole("navigation", { name: "Community tools" })).toBeInTheDocument();
    expect(screen.queryByText(/You haven’t joined any initiatives yet/)).not.toBeInTheDocument();
  });

  it("does not call a failed directory an empty one", async () => {
    stubEmptyCommunity();
    server.use(
      guildHttp.get("/initiatives/directory", () => new HttpResponse(null, { status: 500 }))
    );

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
    stubEmptyCommunity();

    renderHomeAsMember();

    expect(await screen.findByText("Nothing to join yet")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Join" })).not.toBeInTheDocument();
    // A member has no way to make one, so nothing offers it.
    expect(screen.queryByRole("button", { name: /Create initiative/i })).not.toBeInTheDocument();
  });

  it("offers an admin of an empty community the first initiative, not an admin to ask", async () => {
    stubEmptyCommunity();

    renderHome();

    // A community with nothing in it is now the ordinary first minute, and the
    // reader looking at it is the person who fills it. Telling them they
    // haven't joined anything, or that an admin could add them to one, would
    // be sending them to themselves.
    expect(await screen.findByText("This community has no initiatives yet")).toBeInTheDocument();
    expect(screen.getByText("Start the first initiative")).toBeInTheDocument();
    expect(screen.queryByText(/You haven’t joined any initiatives yet/)).not.toBeInTheDocument();
    expect(screen.queryByText(/A community admin or project manager/)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Create initiative/i }));

    // The wizard opens on its first question, not on a form of everything.
    expect(await screen.findByRole("dialog")).toHaveTextContent("What is it called?");
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
