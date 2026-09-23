import {
  CHECK_LIST,
  ELEMENT_TRANSFORMERS,
  MULTILINE_ELEMENT_TRANSFORMERS,
  registerMarkdownShortcuts,
  TEXT_FORMAT_TRANSFORMERS,
  TEXT_MATCH_TRANSFORMERS,
  type Transformer,
} from "@lexical/markdown";
import { defineExtension } from "lexical";

import { createCalloutTransformer } from "@/components/ui/editor/transformers/markdown-callout-transformer";
import { createColumnsTransformer } from "@/components/ui/editor/transformers/markdown-columns-transformer";
import { EMOJI } from "@/components/ui/editor/transformers/markdown-emoji-transformer";
import {
  EXCALIDRAW_EXPORT,
  EXCALIDRAW_IMPORT,
} from "@/components/ui/editor/transformers/markdown-excalidraw-transformer";
import { HR } from "@/components/ui/editor/transformers/markdown-hr-transformer";
import { IMAGE } from "@/components/ui/editor/transformers/markdown-image-transformer";
import { TABLE } from "@/components/ui/editor/transformers/markdown-table-transformer";
import { TWEET } from "@/components/ui/editor/transformers/markdown-tweet-transformer";

export const MARKDOWN_TRANSFORMERS: Transformer[] = [
  // Ahead of the quote it would otherwise be read as.
  createCalloutTransformer(() => MARKDOWN_TRANSFORMERS),
  createColumnsTransformer(() => MARKDOWN_TRANSFORMERS),
  // Ahead of the code block a drawing's fence would otherwise be read as.
  EXCALIDRAW_IMPORT,
  EXCALIDRAW_EXPORT,
  TABLE,
  HR,
  IMAGE,
  EMOJI,
  TWEET,
  CHECK_LIST,
  ...ELEMENT_TRANSFORMERS,
  ...MULTILINE_ELEMENT_TRANSFORMERS,
  ...TEXT_FORMAT_TRANSFORMERS,
  ...TEXT_MATCH_TRANSFORMERS,
];

export const MarkdownShortcutsExtension = defineExtension({
  name: "@initiative/markdown-shortcuts",
  register: (editor) => registerMarkdownShortcuts(editor, MARKDOWN_TRANSFORMERS),
});
