/**
 * A reference shown in full — `![[ ]]` where `#` shows a name.
 *
 * The same reference a `#` link holds (`task:12`), drawn as a callout: what
 * the thing is called now, and what it says about itself. Nothing but the
 * reference is stored, so a rename or a rewritten description reaches every
 * page that embeds it without any of them being edited.
 *
 * Like the link, it serializes `text` — the name it had when written — which
 * is what an export shows and what the search index reads.
 */

import { addClassNamesToElement } from "@lexical/utils";
import {
  $createParagraphNode,
  $isElementNode,
  $isTextNode,
  DecoratorNode,
  type DOMConversionMap,
  type DOMConversionOutput,
  type DOMExportOutput,
  type EditorConfig,
  type LexicalNode,
  type NodeKey,
  type SerializedLexicalNode,
  type Spread,
} from "lexical";
import type { JSX } from "react";

import type { SearchEntityType } from "@/api/generated/initiativeAPI.schemas";
import {
  $createEntityMentionNode,
  type EntityMentionNode,
} from "@/components/ui/editor/nodes/entity-mention-node";
import { ReferenceEmbed } from "@/components/ui/editor/nodes/reference-embed";
import { isSearchEntityType } from "@/lib/entityResolver";

export type SerializedReferenceEmbedNode = Spread<
  {
    entityType: SearchEntityType;
    entityId: number;
    /** The name as it read when written — the export and index fallback. */
    text: string;
  },
  SerializedLexicalNode
>;

const TYPE_ATTR = "data-lexical-reference-embed";
const ID_ATTR = "data-entity-id";

function $convertEmbedElement(domNode: HTMLElement): DOMConversionOutput | null {
  const entityType = domNode.getAttribute(TYPE_ATTR);
  const entityId = Number(domNode.getAttribute(ID_ATTR));
  if (!entityType || !isSearchEntityType(entityType) || !Number.isFinite(entityId)) return null;
  return {
    node: $createReferenceEmbedNode(entityType, entityId, domNode.textContent ?? ""),
  };
}

export class ReferenceEmbedNode extends DecoratorNode<JSX.Element> {
  __entityType: SearchEntityType;
  __entityId: number;
  __text: string;

  static getType(): string {
    return "reference-embed";
  }

  static clone(node: ReferenceEmbedNode): ReferenceEmbedNode {
    return new ReferenceEmbedNode(node.__entityType, node.__entityId, node.__text, node.__key);
  }

  static importJSON(serialized: SerializedReferenceEmbedNode): ReferenceEmbedNode {
    return $createReferenceEmbedNode(serialized.entityType, serialized.entityId, serialized.text);
  }

  constructor(entityType: SearchEntityType, entityId: number, text: string, key?: NodeKey) {
    super(key);
    this.__entityType = entityType;
    this.__entityId = entityId;
    this.__text = text;
  }

  exportJSON(): SerializedReferenceEmbedNode {
    return {
      ...super.exportJSON(),
      entityType: this.__entityType,
      entityId: this.__entityId,
      text: this.__text,
      type: "reference-embed",
      version: 1,
    };
  }

  getEntityType(): SearchEntityType {
    return this.__entityType;
  }

  getEntityId(): number {
    return this.__entityId;
  }

  getTextContent(): string {
    return this.__text;
  }

  /** Drawn as a callout — the same panel, colour and mark. */
  createDOM(config: EditorConfig): HTMLElement {
    const dom = document.createElement("div");
    dom.setAttribute("data-callout", "note");
    if (typeof config.theme.callout === "string") {
      addClassNamesToElement(dom, config.theme.callout);
    }
    return dom;
  }

  updateDOM(): false {
    return false;
  }

  exportDOM(): DOMExportOutput {
    const element = document.createElement("div");
    element.setAttribute(TYPE_ATTR, this.__entityType);
    element.setAttribute(ID_ATTR, String(this.__entityId));
    element.textContent = this.__text;
    return { element };
  }

  /** Reads back what `exportDOM` wrote, so a copied embed pastes live. */
  static importDOM(): DOMConversionMap | null {
    return {
      div: (domNode: HTMLElement) =>
        domNode.hasAttribute(TYPE_ATTR) ? { conversion: $convertEmbedElement, priority: 2 } : null,
    };
  }

  isInline(): false {
    return false;
  }

  isKeyboardSelectable(): true {
    return true;
  }

  decorate(): JSX.Element {
    return (
      <ReferenceEmbed
        entityType={this.__entityType}
        entityId={this.__entityId}
        fallback={this.__text}
        nodeKey={this.getKey()}
      />
    );
  }
}

export function $createReferenceEmbedNode(
  entityType: SearchEntityType,
  entityId: number,
  text: string
): ReferenceEmbedNode {
  return new ReferenceEmbedNode(entityType, entityId, text);
}

export function $isReferenceEmbedNode(
  node: LexicalNode | null | undefined
): node is ReferenceEmbedNode {
  return node instanceof ReferenceEmbedNode;
}

/**
 * Put an embed where something inline stood — a `#` link, or the `![[` typed
 * to ask for one. An embed is a block, so it takes the line over when that
 * leaves nothing else on it and goes on the line after when it does; either
 * way the caret lands after it, to keep writing.
 */
export function $placeEmbed(inline: LexicalNode, embed: ReferenceEmbedNode): void {
  const block = inline.getTopLevelElementOrThrow();
  inline.remove();
  const empty = block
    .getChildren()
    .every((child) => $isTextNode(child) && child.getTextContent().trim() === "");
  if (empty) block.replace(embed);
  else block.insertAfter(embed);
  const next = embed.getNextSibling();
  if ($isElementNode(next)) {
    next.selectStart();
    return;
  }
  const paragraph = $createParagraphNode();
  embed.insertAfter(paragraph);
  paragraph.select();
}

/** A `#` link shown in full instead. */
export function $showAsEmbed(link: EntityMentionNode): void {
  $placeEmbed(
    link,
    $createReferenceEmbedNode(link.getEntityType(), link.getEntityId(), link.getTextContent())
  );
}

/** An embed back to a `#` link, on a line of its own. */
export function $showAsLink(embed: ReferenceEmbedNode): void {
  const paragraph = $createParagraphNode().append(
    $createEntityMentionNode(embed.getEntityType(), embed.getEntityId(), embed.getTextContent())
  );
  embed.replace(paragraph);
  paragraph.selectEnd();
}
