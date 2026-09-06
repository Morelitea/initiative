import { screen, waitFor } from "@testing-library/react";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { buildComment } from "@/__tests__/factories/comment.factory";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import { Tool } from "@/api/generated/initiativeAPI.schemas";

import { ToolCommentsPanel } from "./ToolCommentsPanel";

/** Records the query the panel derived for the thread it wants. */
const captureList = () => {
  const seen: URLSearchParams[] = [];
  server.use(
    guildHttp.get("/comments/", ({ request }) => {
      seen.push(new URL(request.url).searchParams);
      return HttpResponse.json([buildComment({ content: "Existing" })]);
    })
  );
  return seen;
};

describe("ToolCommentsPanel", () => {
  it("derives the thread's query param from the tool", async () => {
    const requests = captureList();

    renderWithProviders(
      <ToolCommentsPanel
        tool={Tool.counter_group}
        entity={{ id: 9, initiative_id: 4, comments_enabled: true }}
      />
    );

    await waitFor(() => expect(requests).toHaveLength(1));
    expect(requests[0].get("counter_group_id")).toBe("9");
  });

  it("uses the same derivation for a different tool, with no per-tool wiring", async () => {
    const requests = captureList();

    renderWithProviders(
      <ToolCommentsPanel
        tool={Tool.dashboard}
        entity={{ id: 12, initiative_id: 4, comments_enabled: true }}
      />
    );

    await waitFor(() => expect(requests).toHaveLength(1));
    expect(requests[0].get("dashboard_id")).toBe("12");
  });

  it("renders nothing and asks for nothing when the entity has comments off", async () => {
    const requests = captureList();

    const { container } = renderWithProviders(
      <ToolCommentsPanel
        tool={Tool.queue}
        entity={{ id: 3, initiative_id: 4, comments_enabled: false }}
      />
    );

    expect(container).toBeEmptyDOMElement();
    // Nothing to wait on — assert the absence after a tick of the query client.
    await waitFor(() => expect(requests).toHaveLength(0));
  });

  it("shows the thread the entity carries", async () => {
    captureList();

    renderWithProviders(
      <ToolCommentsPanel
        tool={Tool.project}
        entity={{ id: 1, initiative_id: 4, comments_enabled: true }}
      />
    );

    expect(await screen.findByText("Existing")).toBeInTheDocument();
  });
});
