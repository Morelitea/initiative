/**
 * The active tool tab is a path segment, not component state — that is what
 * makes it shareable, survive a reload, and answer the back button. These tests
 * pin the mapping from route to tab, including the two fallbacks that keep a
 * stale link from dead-ending.
 */
import { screen } from "@testing-library/react";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { buildGuild, buildInitiative } from "@/__tests__/factories";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { Tool } from "@/api/generated/initiativeAPI.schemas";

import { InitiativeDetailPage } from "./InitiativeDetailPage";

const INITIATIVE_ID = 7;

const page = () =>
  HttpResponse.json({ items: [], total_count: 0, page: 1, page_size: 20, has_next: false });

/** Every tool list answers the same envelope; the tabs only need it to be empty. */
function stubEverything(permissions: Record<string, boolean> = {}) {
  server.use(
    guildHttp.get("/initiatives/:id", ({ params }) =>
      HttpResponse.json(
        buildInitiative({
          id: Number(params.id),
          name: "Apollo",
          queues_enabled: true,
          dashboards_enabled: true,
          calendars_enabled: true,
          counter_groups_enabled: true,
        })
      )
    ),
    guildHttp.get("/initiatives/:id/my-permissions", () =>
      HttpResponse.json({
        role_id: 1,
        role_name: "member",
        role_display_name: "Member",
        is_manager: false,
        override_share_restrictions: false,
        permissions: {
          projects_enabled: true,
          documents_enabled: true,
          queues_enabled: true,
          dashboards_enabled: true,
          calendars_enabled: true,
          counter_groups_enabled: true,
          ...permissions,
        },
      })
    ),
    guildHttp.get("/projects/", page),
    guildHttp.get("/documents/", page),
    guildHttp.get("/queues/", page),
    guildHttp.get("/counter-groups/", page),
    guildHttp.get("/calendars/", page),
    guildHttp.get("/dashboards/", page)
  );
}

const renderAt = (tool?: Tool) =>
  renderPage(() => <InitiativeDetailPage tool={tool} />, {
    guilds: { activeGuildId: 1, activeGuild: buildGuild({ id: 1, role: "admin" }) },
    initialRoute: "/g/$guildId/i/$initiativeId",
    routeParams: { guildId: "1", initiativeId: String(INITIATIVE_ID) },
  });

/** Radix marks the selected trigger with aria-selected. */
const selectedTab = () =>
  screen.getAllByRole("tab").find((tab) => tab.getAttribute("aria-selected") === "true");

describe("InitiativeDetailPage", () => {
  it("selects the tab the route names", async () => {
    stubEverything();
    renderAt(Tool.queue);

    expect(await screen.findByRole("tab", { name: "Queues" })).toBeInTheDocument();
    expect(selectedTab()).toHaveAccessibleName("Queues");
  });

  it("falls back to the first tab when the route names none", async () => {
    stubEverything();
    renderAt();

    // The tabs follow the registry order, which opens with projects.
    expect(await screen.findByRole("tab", { name: "Projects" })).toBeInTheDocument();
    expect(selectedTab()).toHaveAccessibleName("Projects");
  });

  // A permission change shouldn't dead-end a bookmark someone already has.
  it("falls back to the first available tab for a tool this member can't view", async () => {
    stubEverything({ queues_enabled: false });
    renderAt(Tool.queue);

    expect(await screen.findByRole("tab", { name: "Projects" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Queues" })).not.toBeInTheDocument();
    expect(selectedTab()).toHaveAccessibleName("Projects");
  });

  it("links each tab at its own URL rather than swapping state", async () => {
    stubEverything();
    renderAt(Tool.document);

    const projectsTab = await screen.findByRole("tab", { name: "Projects" });
    expect(projectsTab).toHaveAttribute("href", `/g/1/i/${INITIATIVE_ID}/projects`);
  });
});
