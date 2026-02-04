import {
  $applyNodeReplacement,
  TextNode,
  type DOMConversionMap,
  type DOMConversionOutput,
  type DOMExportOutput,
  type EditorConfig,
  type LexicalNode,
  type NodeKey,
  type SerializedTextNode,
  type Spread,
} from "lexical";

export type SerializedWikilinkNode = Spread<
  {
    documentId: number | null;
    documentTitle: string;
  },
  SerializedTextNode
>;

function $convertWikilinkElement(domNode: HTMLElement): DOMConversionOutput | null {
  const textContent = domNode.textContent;
  const documentId = domNode.getAttribute("data-document-id");

  if (textContent !== null) {
    const node = $createWikilinkNode(textContent, documentId ? parseInt(documentId, 10) : null);
    return {
      node,
    };
  }

  return null;
}

export class WikilinkNode extends TextNode {
  __documentId: number | null;
  __documentTitle: string;

  static getType(): string {
    return "wikilink";
  }

  static clone(node: WikilinkNode): WikilinkNode {
    return new WikilinkNode(node.__documentTitle, node.__documentId, node.__text, node.__key);
  }

  static importJSON(serializedNode: SerializedWikilinkNode): WikilinkNode {
    const node = $createWikilinkNode(serializedNode.documentTitle, serializedNode.documentId);
    node.setTextContent(serializedNode.text);
    node.setFormat(serializedNode.format);
    node.setDetail(serializedNode.detail);
    node.setMode(serializedNode.mode);
    node.setStyle(serializedNode.style);
    return node;
  }

  constructor(documentTitle: string, documentId?: number | null, text?: string, key?: NodeKey) {
    super(text ?? documentTitle, key);
    this.__documentTitle = documentTitle;
    this.__documentId = documentId ?? null;
  }

  exportJSON(): SerializedWikilinkNode {
    return {
      ...super.exportJSON(),
      documentId: this.__documentId,
      documentTitle: this.__documentTitle,
      type: "wikilink",
      version: 1,
    };
  }

  getDocumentId(): number | null {
    return this.__documentId;
  }

  getDocumentTitle(): string {
    return this.__documentTitle;
  }

  isResolved(): boolean {
    return this.__documentId !== null;
  }

  createDOM(config: EditorConfig): HTMLElement {
    const dom = super.createDOM(config);
    // Apply resolved/unresolved styling via CSS classes
    dom.className = this.__documentId
      ? "wikilink wikilink-resolved"
      : "wikilink wikilink-unresolved";
    dom.setAttribute("data-lexical-wikilink", "true");
    if (this.__documentId !== null) {
      dom.setAttribute("data-document-id", String(this.__documentId));
    }
    return dom;
  }

  exportDOM(): DOMExportOutput {
    const element = document.createElement("span");
    element.setAttribute("data-lexical-wikilink", "true");
    if (this.__documentId !== null) {
      element.setAttribute("data-document-id", String(this.__documentId));
    }
    element.textContent = this.__text;
    return { element };
  }

  static importDOM(): DOMConversionMap | null {
    return {
      span: (domNode: HTMLElement) => {
        if (!domNode.hasAttribute("data-lexical-wikilink")) {
          return null;
        }
        return {
          conversion: $convertWikilinkElement,
          priority: 1,
        };
      },
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

export function $createWikilinkNode(
  documentTitle: string,
  documentId?: number | null
): WikilinkNode {
  const wikilinkNode = new WikilinkNode(documentTitle, documentId);
  wikilinkNode.setMode("segmented").toggleDirectionless();
  return $applyNodeReplacement(wikilinkNode);
}

export function $isWikilinkNode(node: LexicalNode | null | undefined): node is WikilinkNode {
  return node instanceof WikilinkNode;
}
