/**
 * A tag's page lists everything carrying it, one tab per tool — a task under
 * the project tool it lives in, a wiki page under wikis — and each row links to
 * the thing itself.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { buildTag } from "@/__tests__/factories";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { SearchEntityType, Tool } from "@/api/generated/initiativeAPI.schemas";

import { TagDetailPage } from "./TagDetailPage";

const tag = buildTag({ id: 3, name: "Urgent" });

const hit = (
  entity_type: SearchEntityType,
  entity_id: number,
  title: string,
  tool: Tool,
  tool_id: number
) => ({ entity_type, entity_id, title, initiative_id: 5, tool, tool_id });

describe("TagDetailPage", () => {
  it("groups what carries the tag by the tool it lives in", async () => {
    server.use(
      guildHttp.get("/tags/:tagId", () => HttpResponse.json(tag)),
      guildHttp.get("/tags/:tagId/entities", () =>
        HttpResponse.json({
          items: [
            hit(SearchEntityType.project, 7, "Rewiring", Tool.project, 7),
            hit(SearchEntityType.task, 9, "Wire the doorbell", Tool.project, 7),
            hit(SearchEntityType.wiki_page, 11, "Rota", Tool.wiki, 4),
          ],
        })
      )
    );

    renderPage(TagDetailPage, {
      initialRoute: "/c/$guildId/tags/$tagId",
      routeParams: { guildId: "1", tagId: String(tag.id) },
    });

    expect(await screen.findByRole("tab", { name: /Projects \(2\)/ })).toBeInTheDocument();
    const wikis = screen.getByRole("tab", { name: /Wikis \(1\)/ });
    expect(screen.queryByRole("tab", { name: /Documents/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Wire the doorbell/ })).toHaveAttribute(
      "href",
      "/c/1/i/5/projects/7/tasks/9"
    );

    await userEvent.click(wikis);
    expect(await screen.findByRole("link", { name: /Rota/ })).toHaveAttribute(
      "href",
      "/c/1/i/5/wikis/4/pages/11"
    );
  });
});
