import { waitFor } from "@testing-library/react";
import {
  $createParagraphNode,
  $createTextNode,
  $getRoot,
  type LexicalEditor,
  type ParagraphNode,
  type SerializedEditorState,
} from "lexical";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import { Editor } from "@/components/documents/editor/editor";
import { $isImageNode } from "@/components/ui/editor/nodes/image-node";

const captionText = (text: string) => ({
  root: {
    type: "root",
    version: 1,
    direction: null,
    format: "",
    indent: 0,
    children: [
      {
        type: "paragraph",
        version: 1,
        direction: null,
        format: "",
        indent: 0,
        children: [
          { type: "text", version: 1, detail: 0, format: 0, mode: "normal", style: "", text },
        ],
      },
    ],
  },
});

const imageWithCaption = (text: string) => ({
  root: {
    type: "root",
    version: 1,
    direction: null,
    format: "",
    indent: 0,
    children: [
      {
        type: "paragraph",
        version: 1,
        direction: null,
        format: "",
        indent: 0,
        children: [
          {
            type: "image",
            version: 1,
            src: "/uploads/picture.png",
            altText: "a picture",
            width: 0,
            height: 0,
            maxWidth: 500,
            showCaption: true,
            caption: { editorState: captionText(text) },
          },
        ],
      },
    ],
  },
});

type Editable = HTMLElement & { __lexicalEditor: LexicalEditor };

const editorsIn = async (container: HTMLElement) =>
  waitFor(() => {
    const document = container.querySelector<Editable>('[data-lexical-editor="true"]');
    const caption = container.querySelector<Editable>(".ImageNode__contentEditable");
    expect(document).not.toBeNull();
    expect(caption).not.toBeNull();
    return { document: document as Editable, caption: caption as Editable };
  });

const captionOf = (state: SerializedEditorState | undefined): string => {
  const paragraph = state?.root.children[0] as { children: { caption?: unknown }[] } | undefined;
  return JSON.stringify(paragraph?.children[0]?.caption ?? null);
};

describe("an image caption", () => {
  beforeEach(() => {
    // The image component waits for its picture to load, which a test page's
    // never does.
    vi.stubGlobal(
      "Image",
      class {
        onload: (() => void) | null = null;
        set src(_value: string) {
          queueMicrotask(() => this.onload?.());
        }
      }
    );
  });

  it("is saved with the document when it is edited", async () => {
    const saved: SerializedEditorState[] = [];
    const { container } = renderPage(() => (
      <Editor
        editorSerializedState={imageWithCaption("Before") as unknown as SerializedEditorState}
        onSerializedChange={(state) => saved.push(state)}
      />
    ));

    const { caption } = await editorsIn(container);
    caption.__lexicalEditor.update(() => {
      $getRoot()
        .clear()
        .append($createParagraphNode().append($createTextNode("After")));
    });

    await waitFor(() => expect(captionOf(saved.at(-1))).toContain("After"));
  });

  it("shows a caption written elsewhere, as collaboration delivers it", async () => {
    const { container } = renderPage(() => (
      <Editor
        editorSerializedState={imageWithCaption("Before") as unknown as SerializedEditorState}
      />
    ));
    const { document, caption } = await editorsIn(container);

    // What a collaborator's edit does here: the image node's caption changes.
    document.__lexicalEditor.update(() => {
      const image = $getRoot().getFirstChildOrThrow<ParagraphNode>().getFirstChild();
      if ($isImageNode(image)) {
        image.setCaptionState(JSON.stringify(captionText("From elsewhere")));
      }
    });

    await waitFor(() => expect(caption).toHaveTextContent("From elsewhere"));
  });
});
