import { CodeHighlightNode, CodeNode } from "@lexical/code";
import { HashtagNode } from "@lexical/hashtag";
import { AutoLinkNode, LinkNode } from "@lexical/link";
import { ListItemNode, ListNode } from "@lexical/list";
import { OverflowNode } from "@lexical/overflow";
import { HorizontalRuleNode } from "@lexical/react/LexicalHorizontalRuleNode";
import { HeadingNode, QuoteNode } from "@lexical/rich-text";
import { TableCellNode, TableNode, TableRowNode } from "@lexical/table";
import { Klass, LexicalNode, LexicalNodeReplacement, ParagraphNode, TextNode } from "lexical";

import { EmbedNode } from "@/components/ui/editor/nodes/embed-node";
import { TweetNode } from "@/components/ui/editor/nodes/embeds/tweet-node";
import { YouTubeNode } from "@/components/ui/editor/nodes/embeds/youtube-node";
import { EmojiNode } from "@/components/ui/editor/nodes/emoji-node";
import { ImageNode } from "@/components/ui/editor/nodes/image-node";
import { KeywordNode } from "@/components/ui/editor/nodes/keyword-node";
import { LayoutContainerNode } from "@/components/ui/editor/nodes/layout-container-node";
import { LayoutItemNode } from "@/components/ui/editor/nodes/layout-item-node";
import { MentionNode } from "@/components/ui/editor/nodes/mention-node";
import { WikilinkNode } from "@/components/ui/editor/nodes/wikilink-node";

export const nodes: ReadonlyArray<Klass<LexicalNode> | LexicalNodeReplacement> = [
  HeadingNode,
  ParagraphNode,
  TextNode,
  QuoteNode,
  ListNode,
  ListItemNode,
  LinkNode,
  OverflowNode as unknown as Klass<LexicalNode> | LexicalNodeReplacement,
  HashtagNode as unknown as Klass<LexicalNode> | LexicalNodeReplacement,
  TableNode,
  TableCellNode,
  TableRowNode,
  CodeNode,
  CodeHighlightNode,
  HorizontalRuleNode,
  MentionNode,
  ImageNode,
  EmojiNode,
  KeywordNode,
  LayoutContainerNode,
  LayoutItemNode,
  AutoLinkNode,
  TweetNode,
  YouTubeNode,
  EmbedNode,
  WikilinkNode,
];
