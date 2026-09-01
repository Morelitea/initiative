/**
 * A live chip in a document: `task:12:status`, rendered as whatever that task's
 * column says right now.
 *
 * A `DecoratorNode` rather than a `TextNode`, because the chip has to re-render
 * when the thing changes and a text node cannot without the document being
 * edited — which in a shared document would be a stream of edits from whoever
 * happened to have it open.
 *
 * It still serializes `text`, and that is deliberate: the export renderers
 * degrade any node carrying `text` to its text, and the search index reads
 * `$.**.text`. So a badge exports and is findable by the label it had when it
 * was inserted, while the app shows the live one. A PDF cannot poll.
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

import type { BadgeKind } from "@/api/generated/initiativeAPI.schemas";
import { BadgeChip } from "@/components/ui/editor/nodes/badge-chip";
import { badgeRef, isBadgeKind } from "@/lib/badges";

export type SerializedBadgeNode = Spread<
  {
    badgeKind: BadgeKind;
    entityId: number;
    /** The label as it read when inserted — what an export shows, and what the
     *  chip falls back to when the thing cannot be read. */
    text: string;
  },
  SerializedLexicalNode
>;

const BADGE_ATTR = "data-lexical-badge";
const ENTITY_ATTR = "data-entity-id";

function $convertBadgeElement(domNode: HTMLElement): DOMConversionOutput | null {
  const badgeKind = domNode.getAttribute(BADGE_ATTR);
  const entityId = Number(domNode.getAttribute(ENTITY_ATTR));
  // A pair this build does not know, or an id that is not one, is left as the
  // text it was rendering — better a stale word than a chip pointing nowhere.
  if (!badgeKind || !isBadgeKind(badgeKind) || !Number.isFinite(entityId)) return null;
  return {
    node: $createBadgeNode(badgeKind, entityId, domNode.textContent ?? ""),
  };
}

export class BadgeNode extends DecoratorNode<JSX.Element> {
  __badgeKind: BadgeKind;
  __entityId: number;
  __text: string;

  static getType(): string {
    return "document-badge";
  }

  static clone(node: BadgeNode): BadgeNode {
    return new BadgeNode(node.__badgeKind, node.__entityId, node.__text, node.__key);
  }

  static importJSON(serialized: SerializedBadgeNode): BadgeNode {
    return $createBadgeNode(serialized.badgeKind, serialized.entityId, serialized.text);
  }

  constructor(badgeKind: BadgeKind, entityId: number, text: string, key?: NodeKey) {
    super(key);
    this.__badgeKind = badgeKind;
    this.__entityId = entityId;
    this.__text = text;
  }

  exportJSON(): SerializedBadgeNode {
    return {
      ...super.exportJSON(),
      badgeKind: this.__badgeKind,
      entityId: this.__entityId,
      text: this.__text,
      type: "document-badge",
      version: 1,
    };
  }

  /** The reference this chip reads — what the plugin collects and asks for. */
  getRef(): string {
    return badgeRef(this.__badgeKind, this.__entityId);
  }

  getBadgeKind(): BadgeKind {
    return this.__badgeKind;
  }

  getTextContent(): string {
    return this.__text;
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
    element.setAttribute(BADGE_ATTR, this.__badgeKind);
    element.setAttribute(ENTITY_ATTR, String(this.__entityId));
    element.textContent = this.__text;
    return { element };
  }

  /** Reads back what `exportDOM` wrote, so a badge survives being copied and
   *  pasted as a live chip rather than arriving as the words it happened to
   *  show. */
  static importDOM(): DOMConversionMap | null {
    return {
      span: (domNode: HTMLElement) => {
        if (!domNode.hasAttribute(BADGE_ATTR)) return null;
        return { conversion: $convertBadgeElement, priority: 1 };
      },
    };
  }

  /** Inline: a badge sits in a sentence, not between paragraphs. */
  isInline(): true {
    return true;
  }

  isKeyboardSelectable(): true {
    return true;
  }

  decorate(): JSX.Element {
    return (
      <BadgeChip badgeKind={this.__badgeKind} entityId={this.__entityId} fallback={this.__text} />
    );
  }
}

export function $createBadgeNode(badgeKind: BadgeKind, entityId: number, text: string): BadgeNode {
  return new BadgeNode(badgeKind, entityId, text);
}

export function $isBadgeNode(node: LexicalNode | null | undefined): node is BadgeNode {
  return node instanceof BadgeNode;
}
