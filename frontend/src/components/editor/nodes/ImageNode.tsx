import { type RefObject, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLexicalNodeSelection } from "@lexical/react/useLexicalNodeSelection";
import { mergeRegister } from "@lexical/utils";
import {
  CLICK_COMMAND,
  COMMAND_PRIORITY_LOW,
  DecoratorNode,
  KEY_BACKSPACE_COMMAND,
  KEY_DELETE_COMMAND,
  type DOMExportOutput,
  type EditorConfig,
  type LexicalEditor,
  type LexicalNode,
  type NodeKey,
  type SerializedLexicalNode,
  $applyNodeReplacement,
  $getNodeByKey,
  $getSelection,
  $insertNodes,
  $isNodeSelection,
  $isRangeSelection,
} from "lexical";

export type SerializedImageNode = SerializedLexicalNode & {
  type: "image";
  version: 1;
  src: string;
  altText?: string;
  width?: number | null;
  height?: number | null;
};

export type InsertImagePayload = {
  src: string;
  altText?: string;
  width?: number | null;
  height?: number | null;
};

const DEFAULT_MIN_WIDTH = 120;

export class ImageNode extends DecoratorNode<JSX.Element> {
  __src: string;
  __altText: string;
  __width: number | null;
  __height: number | null;

  constructor(src: string, altText = "", width: number | null = null, height: number | null = null, key?: NodeKey) {
    super(key);
    this.__src = src;
    this.__altText = altText;
    this.__width = width;
    this.__height = height;
  }

  static getType(): string {
    return "image";
  }

  static clone(node: ImageNode): ImageNode {
    return new ImageNode(node.__src, node.__altText, node.__width, node.__height, node.__key);
  }

  static importJSON(serializedNode: SerializedImageNode): ImageNode {
    return $createImageNode({
      src: serializedNode.src,
      altText: serializedNode.altText,
      width: serializedNode.width ?? null,
      height: serializedNode.height ?? null,
    });
  }

  exportJSON(): SerializedImageNode {
    return {
      src: this.__src,
      altText: this.__altText,
      width: this.__width,
      height: this.__height,
      type: "image",
      version: 1,
    };
  }

  exportDOM(): DOMExportOutput {
    const element = document.createElement("img");
    element.setAttribute("src", this.__src);
    if (this.__altText) {
      element.setAttribute("alt", this.__altText);
    }
    if (this.__width) {
      element.setAttribute("width", String(this.__width));
    }
    if (this.__height) {
      element.setAttribute("height", String(this.__height));
    }
    element.setAttribute("loading", "lazy");
    return { element };
  }

  createDOM(config: EditorConfig): HTMLElement {
    void config;
    return document.createElement("span");
  }

  updateDOM(): boolean {
    return false;
  }

  decorate(editor: LexicalEditor): JSX.Element {
    return (
      <ImageComponent
        src={this.__src}
        altText={this.__altText}
        width={this.__width}
        height={this.__height}
        nodeKey={this.__key}
        editor={editor}
      />
    );
  }

  setWidth(width: number | null): void {
    const writable = this.getWritable();
    writable.__width = width;
  }

  setHeight(height: number | null): void {
    const writable = this.getWritable();
    writable.__height = height;
  }

  getWidth(): number | null {
    return this.__width;
  }

  getHeight(): number | null {
    return this.__height;
  }
}

export const $createImageNode = ({ src, altText = "", width = null, height = null }: InsertImagePayload): ImageNode => {
  const imageNode = new ImageNode(src, altText, width, height);
  return $applyNodeReplacement(imageNode);
};

export const $isImageNode = (node: LexicalNode | null | undefined): node is ImageNode => {
  return node instanceof ImageNode;
};

export const insertImageNode = (editor: LexicalEditor, payload: InsertImagePayload) => {
  editor.update(() => {
    const node = $createImageNode(payload);
    const selection = $getSelection();
    if ($isRangeSelection(selection)) {
      selection.insertNodes([node]);
    } else {
      $insertNodes([node]);
    }
  });
};

type ImageComponentProps = {
  src: string;
  altText: string;
  nodeKey: NodeKey;
  width: number | null;
  height: number | null;
  editor: LexicalEditor;
};

const ImageComponent = ({ src, altText, nodeKey, width, height, editor }: ImageComponentProps) => {
  const [isSelected, setSelected, clearSelection] = useLexicalNodeSelection(nodeKey);
  const [isResizing, setIsResizing] = useState(false);
  const imageRef = useRef<HTMLImageElement | null>(null);
  const isEditable = editor.isEditable();

  const removeNode = useCallback(
    (event: KeyboardEvent | null) => {
      if (!isSelected) {
        return false;
      }
      const selection = $getSelection();
      if ($isNodeSelection(selection)) {
        event?.preventDefault();
        editor.update(() => {
          selection.getNodes().forEach((node) => {
            if ($isImageNode(node)) {
              node.remove();
            }
          });
        });
        return true;
      }
      return false;
    },
    [editor, isSelected]
  );

  useEffect(() => {
    return mergeRegister(
      editor.registerCommand<MouseEvent>(
        CLICK_COMMAND,
        (event) => {
          const target = event.target as Node | null;
          if (imageRef.current && target && imageRef.current.contains(target)) {
            if (!event.shiftKey) {
              clearSelection();
            }
            setSelected(true);
            return true;
          }
          return false;
        },
        COMMAND_PRIORITY_LOW
      ),
      editor.registerCommand(KEY_DELETE_COMMAND, (event) => removeNode(event ?? null), COMMAND_PRIORITY_LOW),
      editor.registerCommand(KEY_BACKSPACE_COMMAND, (event) => removeNode(event ?? null), COMMAND_PRIORITY_LOW)
    );
  }, [editor, setSelected, clearSelection, removeNode]);

  const updateSize = useCallback(
    (nextWidth: number, nextHeight: number | null) => {
      editor.update(() => {
        const node = $getNodeByKey(nodeKey);
        if ($isImageNode(node)) {
          node.setWidth(nextWidth);
          node.setHeight(nextHeight);
        }
      });
    },
    [editor, nodeKey]
  );

  const styleWidth = width ?? undefined;
  const styleHeight = height ?? undefined;

  return (
    <span
      className={`relative inline-flex max-w-full select-none flex-col ${
        isSelected ? "outline outline-2 outline-primary" : ""
      } ${isResizing ? "cursor-ew-resize" : ""}`}
      draggable={false}
    >
      <img
        ref={imageRef}
        src={src}
        alt={altText}
        loading="lazy"
        draggable={false}
        style={{
          width: styleWidth ? `${styleWidth}px` : undefined,
          height: styleHeight ? `${styleHeight}px` : undefined,
          maxWidth: "100%",
        }}
        className="my-2 rounded-lg border border-border bg-card object-contain"
        onClick={(event) => {
          if (!event.shiftKey) {
            clearSelection();
          }
          setSelected(true);
        }}
      />
      {isEditable && isSelected ? (
        <ImageResizer
          imageRef={imageRef}
          onResizeStart={() => setIsResizing(true)}
          onResizeEnd={() => setIsResizing(false)}
          onResize={(nextWidth, nextHeight) => updateSize(nextWidth, nextHeight)}
        />
      ) : null}
    </span>
  );
};

type ImageResizerProps = {
  imageRef: RefObject<HTMLImageElement>;
  onResizeStart: () => void;
  onResizeEnd: () => void;
  onResize: (width: number, height: number | null) => void;
};

const ImageResizer = ({ imageRef, onResize, onResizeEnd, onResizeStart }: ImageResizerProps) => {
  const aspectRatio = useMemo(() => {
    const image = imageRef.current;
    if (!image) {
      return null;
    }
    const { naturalWidth, naturalHeight } = image;
    if (!naturalWidth || !naturalHeight) {
      return null;
    }
    return naturalHeight / naturalWidth;
  }, [imageRef]);

  const handlePointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      event.preventDefault();
      event.stopPropagation();
      const image = imageRef.current;
      if (!image) {
        return;
      }
      onResizeStart();
      const startingWidth = image.getBoundingClientRect().width;
      const pointerId = event.pointerId;
      const startX = event.clientX;

      const handlePointerMove = (moveEvent: PointerEvent) => {
        if (moveEvent.pointerId !== pointerId) {
          return;
        }
        const deltaX = moveEvent.clientX - startX;
        const nextWidth = Math.max(DEFAULT_MIN_WIDTH, startingWidth + deltaX);
        const nextHeight =
          aspectRatio && isFinite(aspectRatio) ? Math.round(nextWidth * aspectRatio) : image.getBoundingClientRect().height;
        onResize(Math.round(nextWidth), nextHeight ?? null);
      };

      const handlePointerUp = (upEvent: PointerEvent) => {
        if (upEvent.pointerId !== pointerId) {
          return;
        }
        onResizeEnd();
        document.removeEventListener("pointermove", handlePointerMove);
        document.removeEventListener("pointerup", handlePointerUp);
      };

      document.addEventListener("pointermove", handlePointerMove);
      document.addEventListener("pointerup", handlePointerUp);
    },
    [aspectRatio, imageRef, onResize, onResizeEnd, onResizeStart]
  );

  return (
    <div className="pointer-events-none absolute inset-0">
      <div className="pointer-events-none absolute inset-0 border-2 border-primary/60" />
      <div
        className="pointer-events-auto absolute -bottom-2 -right-2 h-4 w-4 cursor-se-resize rounded-sm border border-primary bg-background shadow"
        onPointerDown={handlePointerDown}
      />
    </div>
  );
};
