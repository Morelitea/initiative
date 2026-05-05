import { defineExtension } from "lexical";
import {
  CHECK_LIST,
  ELEMENT_TRANSFORMERS,
  MULTILINE_ELEMENT_TRANSFORMERS,
  registerMarkdownShortcuts,
  TEXT_FORMAT_TRANSFORMERS,
  TEXT_MATCH_TRANSFORMERS,
} from "@lexical/markdown";

import { EMOJI } from "@/components/ui/editor/transformers/markdown-emoji-transformer";
import { HR } from "@/components/ui/editor/transformers/markdown-hr-transformer";
import { IMAGE } from "@/components/ui/editor/transformers/markdown-image-transformer";
import { TABLE } from "@/components/ui/editor/transformers/markdown-table-transformer";
import { TWEET } from "@/components/ui/editor/transformers/markdown-tweet-transformer";
import { WIKILINK } from "@/components/ui/editor/transformers/markdown-wikilink-transformer";

export const MARKDOWN_TRANSFORMERS = [
  TABLE,
  HR,
  IMAGE,
  EMOJI,
  TWEET,
  WIKILINK,
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
