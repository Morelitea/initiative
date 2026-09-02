import { screen, waitFor } from "@testing-library/react";
import type { SerializedEditorState } from "lexical";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { Editor } from "@/components/documents/editor/editor";

/**
 * A chip is only a chip if it reads.
 *
 * It renders as a Lexical decorator, which the composer portals in itself — so
 * the answers have to reach it from ABOVE the composer. Mounted anywhere inside
 * it, every chip silently falls back to the words stored beside it and the
 * whole feature reads as a static label. Nothing else in the suite sees that,
 * because every other test asks the pieces rather than the page.
 */

/** A document holding one chip and one plain word. */
const documentWithAChip = (): SerializedEditorState =>
  ({
    root: {
      type: "root",
      version: 1,
      format: "",
      indent: 0,
      direction: null,
      children: [
        {
          type: "paragraph",
          version: 1,
          format: "",
          indent: 0,
          direction: null,
          children: [
            {
              type: "smart-chip",
              version: 1,
              chipKind: "counter:value",
              entityId: 4,
              // What it was called when it was inserted.
              text: "Launch signups",
            },
          ],
        },
      ],
    },
  }) as unknown as SerializedEditorState;

function DocumentUnderTest() {
  return (
    <Editor
      editorSerializedState={documentWithAChip()}
      readOnly
      showToolbar={false}
      initiativeId={7}
      supportsEntityMentions
    />
  );
}

describe("a smart chip in a real document", () => {
  it("shows what the thing is doing now, not the words stored beside it", async () => {
    server.use(
      guildHttp.get("/smart-chips/", ({ request }) => {
        const refs = new URL(request.url).searchParams.getAll("ref");
        // Both questions in one request: the reading, and what it is about.
        expect(refs.sort()).toEqual(["counter:4", "counter:4:value"]);
        return HttpResponse.json({
          items: [
            {
              ref: "counter:4:value",
              entity_type: "counter",
              aspect: "value",
              text: "42 / 100",
              tone: "neutral",
              color: null,
              date: null,
              number: "42",
            },
            {
              ref: "counter:4",
              entity_type: "counter",
              aspect: null,
              text: "Launch signups",
              tone: "neutral",
              color: null,
              date: null,
              number: null,
            },
          ],
        });
      })
    );

    renderPage(DocumentUnderTest);

    await waitFor(() => expect(screen.getByText("42 / 100")).toBeInTheDocument());
    // The stored label is the fallback, and a chip that read is past it.
    expect(screen.queryByText("Launch signups")).not.toBeInTheDocument();
  });

  it("falls back to the stored label when the thing cannot be read", async () => {
    server.use(guildHttp.get("/smart-chips/", () => HttpResponse.json({ items: [] })));

    renderPage(DocumentUnderTest);

    await waitFor(() => expect(screen.getByText("Launch signups")).toBeInTheDocument());
  });
});
