/**
 * The template picker on the new-document dialog.
 *
 * It is backed by the guild lookup, which matches words — and before anything
 * is typed there are none, so the picker opened on "No templates available" in
 * a community with plenty of them. What it opens on now is the recent list,
 * asked for blueprints, which is the only way it can say that templates exist
 * at all.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { CreateDocumentDialog } from "@/components/documents/CreateDocumentDialog";

const page = () => () => <CreateDocumentDialog open onOpenChange={() => {}} initiativeId={7} />;

describe("CreateDocumentDialog", () => {
  it("offers templates before anything is typed", async () => {
    const asked: URL[] = [];
    server.use(
      guildHttp.get("/search/recent", ({ request }) => {
        asked.push(new URL(request.url));
        return HttpResponse.json([
          {
            entity_type: "document",
            entity_id: 12,
            title: "Session prep",
            initiative_id: 7,
            tool: "document",
            tool_id: 12,
          },
        ]);
      })
    );

    renderPage(page());

    await userEvent.click(await screen.findByRole("combobox", { name: /start from template/i }));
    expect(await screen.findByText("Session prep")).toBeInTheDocument();

    // Narrowed the same way typing would narrow it, so the list it opens on
    // can hold nothing its own search would refuse to find.
    await waitFor(() => expect(asked.length).toBeGreaterThan(0));
    expect(asked[0].searchParams.get("template")).toBe("true");
    expect(asked[0].searchParams.getAll("types")).toEqual(["document"]);
  });
});
