import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { LexicalExtensionComposer } from "@lexical/react/LexicalExtensionComposer";
import { screen, waitFor } from "@testing-library/react";
import { $createParagraphNode, $createTextNode, $getRoot, type LexicalEditor } from "lexical";
import { HttpResponse } from "msw";
import { useMemo } from "react";
import { describe, expect, it } from "vitest";

import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { documentExtension } from "@/components/documents/editor/document-extension";
import { Plugins } from "@/components/documents/editor/plugins";
import { TooltipProvider } from "@/components/ui/tooltip";
import { SmartChipScope } from "@/hooks/useSmartChips";

/**
 * `#` and the smart-chip picker, in a real document.
 *
 * Both are scoped to the document's own initiative, so a guild full of matching
 * work can still answer nothing — and when it did, neither surface rendered
 * anything at all. A reader saw an unchanged caret and an empty box and
 * reasonably concluded the feature was broken. What is asserted here is that an
 * empty answer LOOKS like an answer.
 */

const suggestion = {
  entity_type: "task",
  entity_id: 12,
  title: "Ship the release",
  initiative_id: 7,
  tool: "project",
  tool_id: 3,
};

let editor!: LexicalEditor;

function Grab(): null {
  const [found] = useLexicalComposerContext();
  editor = found;
  return null;
}

function Harness() {
  const extension = useMemo(() => documentExtension({ collaborative: false, editable: true }), []);
  return (
    <SmartChipScope>
      <LexicalExtensionComposer extension={extension} contentEditable={null}>
        <TooltipProvider>
          <Grab />
          <Plugins showToolbar={false} initiativeId={7} supportsEntityMentions />
        </TooltipProvider>
      </LexicalExtensionComposer>
    </SmartChipScope>
  );
}

/** Type into the document the way a person would, via the editor's own API —
 *  `userEvent` cannot drive a Lexical contenteditable under jsdom. */
function type(text: string) {
  editor.update(
    () => {
      const paragraph = $createParagraphNode();
      const node = $createTextNode(text);
      paragraph.append(node);
      $getRoot().clear().append(paragraph);
      node.select(text.length, text.length);
    },
    { discrete: true }
  );
}

describe("probe: # in a document", () => {
  it("opens the picker on a match", async () => {
    server.use(guildHttp.get("/search/suggest", () => HttpResponse.json([suggestion])));

    renderPage(Harness);
    await waitFor(() => expect(editor).toBeTruthy());
    type("#ship");

    await waitFor(() => expect(screen.getByText("Ship the release")).toBeInTheDocument(), {
      timeout: 4000,
    });
  });

  it("says so when nothing in the initiative matches", async () => {
    server.use(guildHttp.get("/search/suggest", () => HttpResponse.json([])));

    renderPage(Harness);
    await waitFor(() => expect(editor).toBeTruthy());
    type("#zzz");

    // The answer, and why the answer might be empty when the guild is not.
    await waitFor(
      () => expect(screen.getByText(/Nothing in this initiative/)).toBeInTheDocument(),
      {
        timeout: 4000,
      }
    );
    expect(screen.getByText(/Only this document.s initiative/)).toBeInTheDocument();
  });
});
