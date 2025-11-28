import {
  DecoratorNode,
  type DOMExportOutput,
  type EditorConfig,
  type LexicalEditor,
  type LexicalNode,
  type NodeKey,
  type SerializedLexicalNode,
  $applyNodeReplacement,
  $getSelection,
  $insertNodes,
  $isRangeSelection,
} from "lexical";

export type SerializedEmbedNode = SerializedLexicalNode & {
  type: "embed";
  version: 1;
  html: string;
};

export type InsertEmbedPayload = {
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

  exportDOM(): DOMExportOutput {
    const wrapper = document.createElement("div");
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

export const $createEmbedNode = ({ html }: InsertEmbedPayload): EmbedNode => {
  const node = new EmbedNode(html);
  return $applyNodeReplacement(node);
};

export const $isEmbedNode = (node: LexicalNode | null | undefined): node is EmbedNode => {
  return node instanceof EmbedNode;
};

export const insertEmbedNode = (editor: LexicalEditor, payload: InsertEmbedPayload) => {
  editor.update(() => {
    const node = $createEmbedNode(payload);
    const selection = $getSelection();
    if ($isRangeSelection(selection)) {
      selection.insertNodes([node]);
    } else {
      $insertNodes([node]);
    }
  });
};
