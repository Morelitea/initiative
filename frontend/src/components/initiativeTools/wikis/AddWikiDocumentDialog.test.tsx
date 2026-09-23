import { screen } from "@testing-library/react";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { buildDocumentSummary } from "@/__tests__/factories";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { AddWikiDocumentDialog } from "./AddWikiDocumentDialog";

describe("AddWikiDocumentDialog", () => {
  it("offers every kind of document, and leaves out what the wiki already holds", async () => {
    let asked: URLSearchParams | null = null;
    const items = [
      buildDocumentSummary({ id: 1, name: "Minutes", document_type: "native" }),
      buildDocumentSummary({
        id: 2,
        name: "proof.pdf",
        document_type: "file",
        original_filename: "proof.pdf",
        file_content_type: "application/pdf",
      }),
      buildDocumentSummary({ id: 3, name: "Budget", document_type: "spreadsheet" }),
      buildDocumentSummary({ id: 4, name: "Already there", document_type: "whiteboard" }),
    ];
    server.use(
      guildHttp.get("/documents/", ({ request }) => {
        asked = new URL(request.url).searchParams;
        return HttpResponse.json({
          items,
          total_count: items.length,
          page: 1,
          page_size: 0,
          has_next: false,
          sort_by: null,
          sort_dir: null,
        });
      })
    );

    renderWithProviders(
      <AddWikiDocumentDialog
        wikiId={9}
        initiativeId={1}
        pages={[{ id: 4, kind: "document" } as never]}
        open
        onOpenChange={() => {}}
      />
    );

    expect(await screen.findByText("proof.pdf")).toBeInTheDocument();
    expect(screen.getByText("Minutes")).toBeInTheDocument();
    expect(screen.getByText("Budget")).toBeInTheDocument();
    expect(screen.queryByText("Already there")).not.toBeInTheDocument();
    expect(asked?.get("document_type")).toBeNull();
  });
});
