import { waitFor } from "@testing-library/react";
import {
  $createParagraphNode,
  $createTextNode,
  $getRoot,
  type LexicalEditor,
  type SerializedEditorState,
} from "lexical";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import { Editor } from "@/components/documents/editor/editor";

const caption = (text: string) => ({
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
            caption: { editorState: caption(text) },
          },
        ],
      },
    ],
  },
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

    const field = await waitFor(() => {
      const element = container.querySelector(".ImageNode__contentEditable");
      expect(element).not.toBeNull();
      return element as HTMLElement & { __lexicalEditor: LexicalEditor };
    });
    field.__lexicalEditor.update(() => {
      $getRoot()
        .clear()
        .append($createParagraphNode().append($createTextNode("After")));
    });

    await waitFor(() => expect(captionOf(saved.at(-1))).toContain("After"));
  });
});
