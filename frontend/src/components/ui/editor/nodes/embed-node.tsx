/**
 * Legacy EmbedNode for backwards compatibility with old document content.
 * New embeds should use YouTubeNode or TweetNode instead.
 */
import {
  DecoratorNode,
  type DOMConversionMap,
  type DOMConversionOutput,
  type DOMExportOutput,
  type EditorConfig,
  type LexicalEditor,
  type LexicalNode,
  type NodeKey,
  type SerializedLexicalNode,
  $applyNodeReplacement,
} from "lexical";

export type SerializedEmbedNode = SerializedLexicalNode & {
  type: "embed";
  version: 1;
  html: string;
};

export class EmbedNode extends DecoratorNode<JSX.Element> {
  __html: string;

  constructor(html: string, key?: NodeKey) {
    super(key);
    this.__html = html;
  }

  static getType(): string {
    return "embed";
  }

  static clone(node: EmbedNode): EmbedNode {
    return new EmbedNode(node.__html, node.__key);
  }

  static importJSON(serializedNode: SerializedEmbedNode): EmbedNode {
    return $createEmbedNode({ html: serializedNode.html });
  }

  exportJSON(): SerializedEmbedNode {
    return {
      html: this.__html,
      type: "embed",
      version: 1,
    };
  }

  static importDOM(): DOMConversionMap | null {
    return {
      div: (domNode: Node) => {
        if (!(domNode instanceof HTMLElement)) {
          return null;
        }
        if (domNode.getAttribute("data-lexical-embed") !== "true") {
          return null;
        }
        return {
          conversion: convertEmbedElement,
          priority: 1,
        };
      },
    };
  }

  exportDOM(): DOMExportOutput {
    const wrapper = document.createElement("div");
    wrapper.setAttribute("data-lexical-embed", "true");
    wrapper.innerHTML = this.__html;
    return { element: wrapper };
  }

  createDOM(config: EditorConfig): HTMLElement {
    void config;
    return document.createElement("div");
  }

  updateDOM(): boolean {
    return false;
  }

  decorate(editor: LexicalEditor): JSX.Element {
    void editor;
    return <div dangerouslySetInnerHTML={{ __html: this.__html }} />;
  }
}

export type InsertEmbedPayload = {
  html: string;
};

export const $createEmbedNode = ({ html }: InsertEmbedPayload): EmbedNode => {
  const node = new EmbedNode(html);
  return $applyNodeReplacement(node);
};

export const $isEmbedNode = (node: LexicalNode | null | undefined): node is EmbedNode => {
  return node instanceof EmbedNode;
};

const convertEmbedElement = (domNode: Node): DOMConversionOutput | null => {
  if (!(domNode instanceof HTMLElement)) {
    return null;
  }
  if (domNode.getAttribute("data-lexical-embed") !== "true") {
    return null;
  }
  const html = domNode.innerHTML;
  if (!html.trim()) {
    return null;
  }
  return {
    node: $createEmbedNode({ html }),
  };
};
