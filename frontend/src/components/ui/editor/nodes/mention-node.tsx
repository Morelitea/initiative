/**
 * Somebody named inside a document — `@Ada`.
 *
 * A `DecoratorNode`, for the same reason `EntityMentionNode` is one: the name
 * it shows is read rather than stored, so a person who changes their name is
 * renamed in every sentence that mentions them, in every document, with none
 * of them edited. It also makes the mention a real chip — a link to their
 * profile, and their card on hover — which a `TextNode` could never host.
 *
 * It still serializes `text`, `mentionName` and `mentionUserId`, and that is
 * deliberate: export renderers degrade any node carrying `text` to its text,
 * the search index reads `$.**.text`, and mention notifications are raised off
 * `mentionUserId` (see `extractMentionUserIds`). Documents written when this
 * was a `TextNode` carry exactly those fields, so they load unchanged.
 */

import {
  DecoratorNode,
  type DOMConversionMap,
  type DOMConversionOutput,
  type DOMExportOutput,
  type LexicalNode,
  type NodeKey,
  type SerializedLexicalNode,
  type Spread,
} from "lexical";
import type { JSX } from "react";

import { UserMention } from "@/components/user/UserMention";

export type SerializedMentionNode = Spread<
  {
    mentionName: string;
    mentionUserId?: number | null;
    /** The name as it read when written — the export and index fallback. */
    text: string;
  },
  SerializedLexicalNode
>;

const MENTION_ATTR = "data-lexical-mention";
const USER_ID_ATTR = "data-mention-user-id";

function $convertMentionElement(domNode: HTMLElement): DOMConversionOutput | null {
  const textContent = domNode.textContent;
  if (textContent === null) return null;
  const userId = Number(domNode.getAttribute(USER_ID_ATTR));
  return { node: $createMentionNode(textContent, Number.isFinite(userId) ? userId : null) };
}

export class MentionNode extends DecoratorNode<JSX.Element> {
  __mention: string;
  __mentionUserId: number | null;

  static getType(): string {
    return "mention";
  }

  static clone(node: MentionNode): MentionNode {
    return new MentionNode(node.__mention, node.__mentionUserId, node.__key);
  }

  static importJSON(serializedNode: SerializedMentionNode): MentionNode {
    // `text` is what a document written before this was a decorator carries,
    // and it is the same string either way.
    return $createMentionNode(
      serializedNode.mentionName ?? serializedNode.text ?? "",
      serializedNode.mentionUserId ?? null
    );
  }

  constructor(mentionName: string, mentionUserId?: number | null, key?: NodeKey) {
    super(key);
    this.__mention = mentionName;
    this.__mentionUserId = mentionUserId ?? null;
  }

  exportJSON(): SerializedMentionNode {
    return {
      ...super.exportJSON(),
      mentionName: this.__mention,
      mentionUserId: this.__mentionUserId,
      text: this.__mention,
      type: "mention",
      version: 1,
    };
  }

  getMentionUserId(): number | null {
    return this.__mentionUserId;
  }

  getTextContent(): string {
    return this.__mention;
  }

  createDOM(): HTMLElement {
    const dom = document.createElement("span");
    dom.className = "inline-block align-baseline";
    return dom;
  }

  updateDOM(): false {
    return false;
  }

  exportDOM(): DOMExportOutput {
    const element = document.createElement("span");
    element.setAttribute(MENTION_ATTR, "true");
    if (this.__mentionUserId !== null) {
      element.setAttribute(USER_ID_ATTR, String(this.__mentionUserId));
    }
    element.textContent = this.__mention;
    return { element };
  }

  static importDOM(): DOMConversionMap | null {
    return {
      span: (domNode: HTMLElement) =>
        domNode.hasAttribute(MENTION_ATTR)
          ? { conversion: $convertMentionElement, priority: 1 }
          : null,
    };
  }

  /** Inline: a mention sits in a sentence. */
  isInline(): true {
    return true;
  }

  isKeyboardSelectable(): true {
    return true;
  }

  decorate(): JSX.Element {
    return <UserMention userId={this.__mentionUserId} fallback={this.__mention} />;
  }
}

export function $createMentionNode(
  mentionName: string,
  mentionUserId?: number | null
): MentionNode {
  return new MentionNode(mentionName, mentionUserId);
}

export function $isMentionNode(node: LexicalNode | null | undefined): node is MentionNode {
  return node instanceof MentionNode;
}
