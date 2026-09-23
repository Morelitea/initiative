import { addClassNamesToElement } from "@lexical/utils";
import {
  $applyNodeReplacement,
  type DOMConversionMap,
  type DOMConversionOutput,
  type DOMExportOutput,
  type EditorConfig,
  type ElementDOMSlot,
  ElementNode,
  type LexicalNode,
  type LexicalUpdateJSON,
  type NodeKey,
  type SerializedElementNode,
  type Spread,
} from "lexical";

/** The kinds of callout, each with its own colour and icon. The names are
 * the ones Obsidian writes as `> [!info]`, so a callout survives the trip to
 * markdown and back. */
export const CALLOUT_VARIANTS = ["info", "note", "tip", "success", "warning", "error"] as const;
export type CalloutVariant = (typeof CALLOUT_VARIANTS)[number];

export const isCalloutVariant = (value: unknown): value is CalloutVariant =>
  typeof value === "string" && (CALLOUT_VARIANTS as readonly string[]).includes(value);

/** Other names for the same kinds, as other tools write them. */
const VARIANT_ALIASES: Record<string, CalloutVariant> = {
  abstract: "note",
  summary: "note",
  tldr: "note",
  todo: "info",
  hint: "tip",
  important: "tip",
  check: "success",
  done: "success",
  question: "info",
  help: "info",
  faq: "info",
  caution: "warning",
  attention: "warning",
  failure: "error",
  fail: "error",
  missing: "error",
  danger: "error",
  bug: "error",
  example: "note",
  quote: "note",
  cite: "note",
  panel: "note",
};

/** A callout kind from whatever another tool called it; anything unknown is
 * a plain note rather than a refusal. */
export function calloutVariantFrom(name: string | null | undefined): CalloutVariant {
  const key = (name ?? "").trim().toLowerCase();
  if (isCalloutVariant(key)) {
    return key;
  }
  return VARIANT_ALIASES[key] ?? "note";
}

export type SerializedCalloutNode = Spread<{ variant: CalloutVariant }, SerializedElementNode>;

const BODY_CLASS = "callout-body";

function $convertCalloutElement(domNode: HTMLElement): DOMConversionOutput | null {
  const variant = calloutVariantFrom(domNode.getAttribute("data-callout"));
  return { node: $createCalloutNode(variant) };
}

/**
 * A callout: a coloured panel with an icon, holding ordinary blocks —
 * paragraphs, lists, code — rather than a single run of text the way a quote
 * does. Its children are its body; the icon is decoration the editor draws
 * around them, never text in the document.
 */
export class CalloutNode extends ElementNode {
  __variant: CalloutVariant;

  static getType(): string {
    return "callout";
  }

  static clone(node: CalloutNode): CalloutNode {
    return new CalloutNode(node.__variant, node.__key);
  }

  constructor(variant: CalloutVariant = "info", key?: NodeKey) {
    super(key);
    this.__variant = variant;
  }

  static importJSON(serialized: SerializedCalloutNode): CalloutNode {
    return $createCalloutNode().updateFromJSON(serialized);
  }

  updateFromJSON(serialized: LexicalUpdateJSON<SerializedCalloutNode>): this {
    return super.updateFromJSON(serialized).setVariant(calloutVariantFrom(serialized.variant));
  }

  exportJSON(): SerializedCalloutNode {
    return {
      ...super.exportJSON(),
      type: "callout",
      variant: this.getVariant(),
      version: 1,
    };
  }

  static importDOM(): DOMConversionMap | null {
    return {
      div: (domNode: HTMLElement) =>
        domNode.hasAttribute("data-callout")
          ? { conversion: $convertCalloutElement, priority: 2 }
          : null,
    };
  }

  exportDOM(): DOMExportOutput {
    const element = document.createElement("div");
    element.setAttribute("data-callout", this.getVariant());
    return { element };
  }

  createDOM(config: EditorConfig): HTMLElement {
    const dom = document.createElement("div");
    dom.setAttribute("data-callout", this.__variant);
    if (typeof config.theme.callout === "string") {
      addClassNamesToElement(dom, config.theme.callout);
    }
    const icon = document.createElement("span");
    icon.className = "callout-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.contentEditable = "false";
    const body = document.createElement("div");
    body.className = BODY_CLASS;
    dom.append(icon, body);
    return dom;
  }

  getDOMSlot(element: HTMLElement): ElementDOMSlot<HTMLElement> {
    const body = element.querySelector<HTMLElement>(`:scope > .${BODY_CLASS}`);
    const slot = super.getDOMSlot(element);
    return body ? slot.withElement(body) : slot;
  }

  updateDOM(prevNode: this, dom: HTMLElement): boolean {
    if (prevNode.__variant !== this.__variant) {
      dom.setAttribute("data-callout", this.__variant);
    }
    return false;
  }

  getVariant(): CalloutVariant {
    return this.getLatest().__variant;
  }

  setVariant(variant: CalloutVariant): this {
    const writable = this.getWritable();
    writable.__variant = variant;
    return writable;
  }

  isShadowRoot(): boolean {
    return true;
  }

  canBeEmpty(): boolean {
    return false;
  }
}

export function $createCalloutNode(variant: CalloutVariant = "info"): CalloutNode {
  return $applyNodeReplacement(new CalloutNode(variant));
}

export function $isCalloutNode(node: LexicalNode | null | undefined): node is CalloutNode {
  return node instanceof CalloutNode;
}
