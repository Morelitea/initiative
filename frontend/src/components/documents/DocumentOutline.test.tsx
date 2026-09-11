import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { LexicalExtensionComposer } from "@lexical/react/LexicalExtensionComposer";
import type { TableOfContentsEntry } from "@lexical/react/LexicalTableOfContentsPlugin";
import { $createHeadingNode, type HeadingTagType } from "@lexical/rich-text";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { $createTextNode, $getRoot, type LexicalEditor } from "lexical";
import { useMemo } from "react";
import { describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import {
  buildOutlineTree,
  DocumentOutlinePanel,
  DocumentOutlineScope,
  DocumentOutlineTracker,
} from "@/components/documents/DocumentOutline";
import { documentExtension } from "@/components/documents/editor/document-extension";
import { Plugins } from "@/components/documents/editor/plugins";
import { TooltipProvider } from "@/components/ui/tooltip";
import { SmartChipScope } from "@/hooks/useSmartChips";

const entry = (key: string, text: string, tag: HeadingTagType): TableOfContentsEntry => [
  key,
  text,
  tag,
];

describe("buildOutlineTree", () => {
  it("files each heading under the nearest shallower one", () => {
    const tree = buildOutlineTree([
      entry("1", "Overview", "h1"),
      entry("2", "Details", "h2"),
      entry("3", "Edge cases", "h3"),
      entry("4", "Appendix", "h1"),
    ]);

    expect(tree.map((node) => node.text)).toEqual(["Overview", "Appendix"]);
    expect(tree[0].children.map((node) => node.text)).toEqual(["Details"]);
    expect(tree[0].children[0].children.map((node) => node.text)).toEqual(["Edge cases"]);
    expect(tree[1].children).toEqual([]);
  });

  it("puts the shallowest headings it actually has at the top", () => {
    const tree = buildOutlineTree([
      entry("1", "First", "h2"),
      entry("2", "Under first", "h3"),
      entry("3", "Second", "h2"),
    ]);

    expect(tree.map((node) => node.text)).toEqual(["First", "Second"]);
    expect(tree[0].children.map((node) => node.text)).toEqual(["Under first"]);
  });

  it("keeps a skipped level as nesting rather than inventing a heading", () => {
    const tree = buildOutlineTree([entry("1", "Overview", "h1"), entry("2", "Deep", "h3")]);

    expect(tree).toHaveLength(1);
    expect(tree[0].children.map((node) => node.text)).toEqual(["Deep"]);
  });

  it("closes every deeper heading when a shallower one arrives", () => {
    const tree = buildOutlineTree([
      entry("1", "A", "h3"),
      entry("2", "B", "h4"),
      entry("3", "C", "h5"),
      entry("4", "D", "h3"),
    ]);

    expect(tree.map((node) => node.text)).toEqual(["A", "D"]);
    expect(tree[0].children[0].children.map((node) => node.text)).toEqual(["C"]);
  });
});

let editor!: LexicalEditor;

function Grab(): null {
  const [found] = useLexicalComposerContext();
  editor = found;
  return null;
}

/** The document page's arrangement: the body editor and the contents list
 *  under one scope, which is the only thing joining them. */
function Harness() {
  const extension = useMemo(() => documentExtension({ collaborative: false, editable: true }), []);

  return (
    <DocumentOutlineScope>
      <SmartChipScope>
        <LexicalExtensionComposer extension={extension} contentEditable={null}>
          <TooltipProvider>
            <Grab />
            <Plugins showToolbar={false} initiativeId={7} />
            <DocumentOutlineTracker />
          </TooltipProvider>
        </LexicalExtensionComposer>
      </SmartChipScope>
      <DocumentOutlinePanel isOpen onOpenChange={() => {}} />
    </DocumentOutlineScope>
  );
}

const writeHeadings = (headings: [HeadingTagType, string][]) => {
  editor.update(
    () => {
      const root = $getRoot().clear();
      for (const [tag, text] of headings) {
        root.append($createHeadingNode(tag).append($createTextNode(text)));
      }
    },
    { discrete: true }
  );
};

describe("the document's contents", () => {
  it("lists the body's headings, nested", async () => {
    renderPage(Harness);
    await waitFor(() => expect(editor).toBeTruthy());

    writeHeadings([
      ["h1", "Overview"],
      ["h2", "Details"],
    ]);

    const overview = await screen.findByRole("button", { name: "Overview" });
    const section = overview.closest("li");
    expect(section).not.toBeNull();
    expect(
      within(section as HTMLElement).getByRole("button", { name: "Details" })
    ).toBeInTheDocument();
  });

  it("scrolls to a heading when it is chosen", async () => {
    const scrollIntoView = vi
      .spyOn(HTMLElement.prototype, "scrollIntoView")
      .mockImplementation(() => {});

    renderPage(Harness);
    await waitFor(() => expect(editor).toBeTruthy());

    writeHeadings([
      ["h1", "Overview"],
      ["h1", "Appendix"],
    ]);

    const appendix = await screen.findByRole("button", { name: "Appendix" });
    await userEvent.click(appendix);

    const heading = editor.getEditorState().read(() => $getRoot().getLastChild()?.getKey() ?? null);
    expect(heading).not.toBeNull();
    expect(scrollIntoView).toHaveBeenCalled();
    expect(scrollIntoView.mock.instances[0]).toBe(editor.getElementByKey(heading as string));

    scrollIntoView.mockRestore();
  });

  it("says so when the document has no headings", async () => {
    renderPage(Harness);
    await waitFor(() => expect(editor).toBeTruthy());

    expect(await screen.findByText("Headings you add appear here.")).toBeInTheDocument();
  });
});
