/**
 * A thing named inside a document — `#task`, `#queue`, `#dashboard`.
 *
 * A `TextNode` subclass, which is what makes it free everywhere downstream: the
 * export renderers degrade an unknown node with `text` to its text, and the
 * search index reads `$.**.text`, so a mention is exported and indexed by its
 * label without either side learning about this node.
 *
 * Deliberately NOT the same node as an `@` mention of a person. A person's
 * mention is rewritten when their account is anonymized and is read back to
 * work out who to notify; a thing has neither. One node doing both would mean
 * every walker asking which kind it was holding.
 */

import {
  $applyNodeReplacement,
  type DOMConversionMap,
  type DOMConversionOutput,
  type DOMExportOutput,
  type EditorConfig,
  type LexicalNode,
  type NodeKey,
  type SerializedTextNode,
  type Spread,
  TextNode,
} from "lexical";

import type { SearchEntityType } from "@/api/generated/initiativeAPI.schemas";

export type SerializedEntityMentionNode = Spread<
  {
    entityType: SearchEntityType;
    entityId: number;
  },
  SerializedTextNode
>;

const ENTITY_MENTION_ATTR = "data-lexical-entity-mention";
const ENTITY_ID_ATTR = "data-entity-id";

function $convertEntityMentionElement(domNode: HTMLElement): DOMConversionOutput | null {
  const text = domNode.textContent;
  const entityType = domNode.getAttribute(ENTITY_MENTION_ATTR);
  const entityId = Number(domNode.getAttribute(ENTITY_ID_ATTR));
  if (!text || !entityType || !Number.isFinite(entityId)) return null;
  return { node: $createEntityMentionNode(entityType as SearchEntityType, entityId, text) };
}

export class EntityMentionNode extends TextNode {
  __entityType: SearchEntityType;
  __entityId: number;

  static getType(): string {
    return "entity-mention";
  }

  static clone(node: EntityMentionNode): EntityMentionNode {
    return new EntityMentionNode(node.__entityType, node.__entityId, node.__text, node.__key);
  }

  static importJSON(serialized: SerializedEntityMentionNode): EntityMentionNode {
    const node = $createEntityMentionNode(
      serialized.entityType,
      serialized.entityId,
      serialized.text
    );
    node.setFormat(serialized.format);
    node.setDetail(serialized.detail);
    node.setMode(serialized.mode);
    node.setStyle(serialized.style);
    return node;
  }

  constructor(entityType: SearchEntityType, entityId: number, text: string, key?: NodeKey) {
    super(text, key);
    this.__entityType = entityType;
    this.__entityId = entityId;
  }

  exportJSON(): SerializedEntityMentionNode {
    return {
      ...super.exportJSON(),
      entityType: this.__entityType,
      entityId: this.__entityId,
      type: "entity-mention",
      version: 1,
    };
  }

  getEntityType(): SearchEntityType {
    return this.__entityType;
  }

  getEntityId(): number {
    return this.__entityId;
  }

  createDOM(config: EditorConfig): HTMLElement {
    const dom = super.createDOM(config);
    dom.className = "entity-mention cursor-pointer rounded bg-primary/10 px-1 text-primary";
    dom.setAttribute(ENTITY_MENTION_ATTR, this.__entityType);
    dom.setAttribute(ENTITY_ID_ATTR, String(this.__entityId));
    return dom;
  }

  exportDOM(): DOMExportOutput {
    const element = document.createElement("span");
    element.setAttribute(ENTITY_MENTION_ATTR, this.__entityType);
    element.setAttribute(ENTITY_ID_ATTR, String(this.__entityId));
    element.textContent = this.__text;
    return { element };
  }

  static importDOM(): DOMConversionMap | null {
    return {
      span: (domNode: HTMLElement) =>
        domNode.hasAttribute(ENTITY_MENTION_ATTR)
          ? { conversion: $convertEntityMentionElement, priority: 1 }
          : null,
    };
  }

  isTextEntity(): true {
    return true;
  }

  canInsertTextBefore(): boolean {
    return false;
  }

  canInsertTextAfter(): boolean {
    return false;
  }
}

export function $createEntityMentionNode(
  entityType: SearchEntityType,
  entityId: number,
  label: string
): EntityMentionNode {
  const node = new EntityMentionNode(entityType, entityId, label);
  node.setMode("segmented").toggleDirectionless();
  return $applyNodeReplacement(node);
}

export function $isEntityMentionNode(
  node: LexicalNode | null | undefined
): node is EntityMentionNode {
  return node instanceof EntityMentionNode;
}
