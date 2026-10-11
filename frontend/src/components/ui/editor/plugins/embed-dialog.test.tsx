import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { LexicalExtensionComposer } from "@lexical/react/LexicalExtensionComposer";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { $getRoot, type LexicalEditor } from "lexical";
import { useMemo } from "react";
import { describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import { documentExtension } from "@/components/ui/editor/document-extension";
import { $isReferenceEmbedNode } from "@/components/ui/editor/nodes/reference-embed-node";
import { EmbedDialog } from "@/components/ui/editor/plugins/embed-dialog";
import { TooltipProvider } from "@/components/ui/tooltip";

let editor!: LexicalEditor;

function Harness({ onClose }: { onClose: () => void }) {
  const extension = useMemo(() => documentExtension({ collaborative: false, editable: true }), []);
  return (
    <LexicalExtensionComposer extension={extension} contentEditable={null}>
      <TooltipProvider>
        <Dialog onClose={onClose} />
      </TooltipProvider>
    </LexicalExtensionComposer>
  );
}

function Dialog({ onClose }: { onClose: () => void }) {
  const [found] = useLexicalComposerContext();
  editor = found;
  return <EmbedDialog activeEditor={found} initiativeId={7} onClose={onClose} />;
}

const embeds = () =>
  editor.getEditorState().read(() =>
    $getRoot()
      .getChildren()
      .filter($isReferenceEmbedNode)
      .map((node) => node.exportJSON())
  );

describe("choosing what an embed shows", () => {
  it("inserts a count of the tasks a filter matches in the page's initiative", async () => {
    const onClose = vi.fn();
    renderPage(() => <Harness onClose={onClose} />);

    await userEvent.click(await screen.findByRole("tab", { name: "Tasks matching a filter" }));
    await userEvent.type(screen.getByLabelText("Label"), "Open launch tasks");
    await userEvent.click(screen.getByRole("radio", { name: "Count" }));
    await userEvent.click(screen.getByRole("button", { name: "Embed" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    const [embed] = embeds();
    expect(embed.text).toBe("Open launch tasks");
    expect(embed.display).toEqual({ mode: "count" });
    expect(embed.query).toMatchObject({ initiative_id: 7, project_id: null });
  });
});
