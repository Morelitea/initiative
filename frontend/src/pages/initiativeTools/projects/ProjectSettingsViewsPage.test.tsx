/**
 * The project's views list in settings. Every change saves the whole set, so
 * the first one stores the shipped views with the change in it.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { buildSavedViewSet, buildToolView, buildToolViewSet } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { ToolViewSetRead, ToolViewSetWrite } from "@/api/generated/initiativeAPI.schemas";
import { ProjectSettingsViewsPage } from "@/pages/initiativeTools/projects/ProjectSettingsViewsPage";

let saves: ToolViewSetWrite[] = [];

const withSet = (set: ToolViewSetRead) =>
  server.use(communityHttp.get("/views/", () => HttpResponse.json(set)));

const page = () =>
  renderPage(ProjectSettingsViewsPage, {
    initialRoute: "/projects/$projectId/settings/views",
    routeParams: { projectId: "1" },
  });

/** The shipped views after the first three, as (slug, name, default) rows. */
const FILTER_VIEWS = [
  ["incomplete", "Incomplete", false],
  ["unassigned", "Unassigned", false],
  ["mine", "Mine", false],
];

/** The views saved last, as (slug, name, default) rows. */
const lastSaved = () =>
  saves.at(-1)?.views.map((view) => [view.slug, view.name, view.is_default ?? false]);

beforeEach(() => {
  saves = [];
  server.use(
    communityHttp.put("/views/", async ({ request }) => {
      const body = (await request.json()) as ToolViewSetWrite;
      saves.push(body);
      return HttpResponse.json(buildSavedViewSet(body));
    })
  );
});

describe("ProjectSettingsViewsPage", () => {
  it("tells someone who may not configure the project's views so", async () => {
    withSet(buildToolViewSet({ can_configure: false }));
    page();

    expect(await screen.findByText(/permission required/i)).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /view name/i })).toBeNull();
  });

  it("stores the shipped views, under their own names, with a rename in them", async () => {
    const user = userEvent.setup();
    page();

    const [table] = await screen.findAllByRole("textbox", { name: /view name/i });
    await user.clear(table);
    await user.type(table, "Everything{Enter}");

    await waitFor(() =>
      expect(lastSaved()).toEqual([
        ["table", "Everything", true],
        ["board", "Board", false],
        ["calendar", "Calendar", false],
        ...FILTER_VIEWS,
      ])
    );
  });

  it("moves a view up the list", async () => {
    const user = userEvent.setup();
    page();

    await user.click(await screen.findByRole("button", { name: /move “Board” up/i }));

    await waitFor(() =>
      expect(lastSaved()?.map(([slug]) => slug)).toEqual([
        "board",
        "table",
        "calendar",
        "incomplete",
        "unassigned",
        "mine",
      ])
    );
  });

  it("makes another view the default, and only that one", async () => {
    const user = userEvent.setup();
    page();

    const defaults = await screen.findAllByRole("button", { name: /^default$/i });
    await user.click(defaults[2]);

    await waitFor(() =>
      expect(lastSaved()?.map(([slug, , isDefault]) => [slug, isDefault])).toEqual([
        ["table", false],
        ["board", false],
        ["calendar", true],
        ...FILTER_VIEWS.map(([slug, , isDefault]) => [slug, isDefault]),
      ])
    );
  });

  it("passes the default on when the default view is deleted", async () => {
    const user = userEvent.setup();
    page();

    await user.click(await screen.findByRole("button", { name: /delete “Table”/i }));
    await user.click(await screen.findByRole("button", { name: /^delete$/i }));

    await waitFor(() =>
      expect(lastSaved()).toEqual([
        ["board", "Board", true],
        ["calendar", "Calendar", false],
        ...FILTER_VIEWS,
      ])
    );
  });

  it("waits for one save before taking another", async () => {
    let answer = () => {};
    server.use(
      communityHttp.put("/views/", async ({ request }) => {
        const body = (await request.json()) as ToolViewSetWrite;
        saves.push(body);
        await new Promise<void>((resolve) => {
          answer = resolve;
        });
        return HttpResponse.json(buildSavedViewSet(body));
      })
    );
    const user = userEvent.setup();
    page();

    await user.click(await screen.findByRole("button", { name: /move “Board” up/i }));
    await waitFor(() => expect(saves).toHaveLength(1));
    const moveMine = screen.getByRole("button", { name: /move “Mine” up/i });
    expect(moveMine).toBeDisabled();
    expect(screen.getByRole("button", { name: /delete “Mine”/i })).toBeDisabled();

    answer();
    await waitFor(() => expect(moveMine).toBeEnabled());
    expect(saves).toHaveLength(1);
  });

  it("keeps the last view, which the set cannot be without", async () => {
    withSet(
      buildToolViewSet({
        stored: true,
        views: [buildToolView({ slug: "only", name: "Only", is_default: true })],
      })
    );
    page();

    expect(await screen.findByRole("button", { name: /delete “Only”/i })).toBeDisabled();
  });
});
