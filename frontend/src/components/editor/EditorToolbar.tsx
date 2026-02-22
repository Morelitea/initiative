import { type ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  $createParagraphNode,
  $getSelection,
  $isElementNode,
  $isRangeSelection,
  $isTextNode,
  $setSelection,
  type RangeSelection,
  CAN_REDO_COMMAND,
  CAN_UNDO_COMMAND,
  COMMAND_PRIORITY_LOW,
  INDENT_CONTENT_COMMAND,
  FORMAT_ELEMENT_COMMAND,
  FORMAT_TEXT_COMMAND,
  OUTDENT_CONTENT_COMMAND,
  REDO_COMMAND,
  SELECTION_CHANGE_COMMAND,
  UNDO_COMMAND,
} from "lexical";
import { INSERT_HORIZONTAL_RULE_COMMAND } from "@lexical/react/LexicalHorizontalRuleNode";
import {
  $createHeadingNode,
  $createQuoteNode,
  $isHeadingNode,
  $isQuoteNode,
} from "@lexical/rich-text";
import { $setBlocksType, $patchStyleText } from "@lexical/selection";
import { TOGGLE_LINK_COMMAND } from "@lexical/link";
import { $createCodeNode } from "@lexical/code";
import {
  $deleteTableColumnAtSelection,
  $deleteTableRowAtSelection,
  $insertTableColumnAtSelection,
  $insertTableRowAtSelection,
  $isTableCellNode,
  INSERT_TABLE_COMMAND,
} from "@lexical/table";
import {
  INSERT_ORDERED_LIST_COMMAND,
  INSERT_UNORDERED_LIST_COMMAND,
  INSERT_CHECK_LIST_COMMAND,
  REMOVE_LIST_COMMAND,
  $isListNode,
} from "@lexical/list";
import { $findMatchingParent } from "@lexical/utils";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import {
  AlignCenter,
  AlignJustify,
  AlignLeft,
  AlignRight,
  Bold,
  Code2,
  Italic,
  Link as LinkIcon,
  List,
  ListChecks,
  ListOrdered,
  IndentDecrease,
  IndentIncrease,
} from "lucide-react";
import { toast } from "sonner";

import { uploadAttachment } from "@/lib/attachmentUtils";
import { insertImageNode } from "@/components/editor/nodes/ImageNode";
import { insertEmbedNode } from "@/components/editor/nodes/EmbedNode";
import {
  type BlockType,
  type Alignment,
  type ListType,
  FONT_SIZE_OPTIONS,
  DEFAULT_FONT_SIZE,
  extractFontSize,
  replaceFontSizeInStyle,
  mergeRegisters,
  extractYouTubeId,
} from "@/components/editor/toolbar/editorToolbarUtils";
import { EditorMobileOverflowMenu } from "@/components/editor/toolbar/EditorMobileOverflowMenu";
import { EditorInsertMenu } from "@/components/editor/toolbar/EditorInsertMenu";
import { EditorTableMenu } from "@/components/editor/toolbar/EditorTableMenu";

export const EditorToolbar = ({ readOnly }: { readOnly?: boolean }) => {
  const [editor] = useLexicalComposerContext();
  const { t } = useTranslation("documents");
  const [canUndo, setCanUndo] = useState(false);
  const [canRedo, setCanRedo] = useState(false);
  const [blockType, setBlockType] = useState<BlockType>("paragraph");
  const [fontSize, setFontSize] = useState<string>("16px");
  const [isUnderline, setIsUnderline] = useState(false);
  const [isBold, setIsBold] = useState(false);
  const [isItalic, setIsItalic] = useState(false);
  const [isCodeBlock, setIsCodeBlock] = useState(false);
  const [alignment, setAlignment] = useState<Alignment>("left");
  const [listType, setListType] = useState<ListType>("none");
  const [isInTable, setIsInTable] = useState(false);
  const [isImageUploading, setIsImageUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const blockOptions = useMemo(
    () => [
      { label: t("editor.blockNormal"), value: "paragraph" as BlockType },
      { label: t("editor.blockH1"), value: "h1" as BlockType },
      { label: t("editor.blockH2"), value: "h2" as BlockType },
      { label: t("editor.blockH3"), value: "h3" as BlockType },
      { label: t("editor.blockQuote"), value: "quote" as BlockType },
      { label: t("editor.blockCode"), value: "code" as BlockType },
    ],
    [t]
  );

  const cloneCurrentSelection = useCallback((): RangeSelection | null => {
    return editor.getEditorState().read(() => {
      const selection = $getSelection();
      return $isRangeSelection(selection) ? selection.clone() : null;
    });
  }, [editor]);

  const updateToolbar = useCallback(() => {
    editor.getEditorState().read(() => {
      const selection = $getSelection();
      if (!$isRangeSelection(selection)) {
        setIsUnderline(false);
        setIsBold(false);
        setIsItalic(false);
        setIsCodeBlock(false);
        setListType("none");
        setBlockType("paragraph");
        setAlignment("left");
        setIsInTable(false);
        setFontSize(DEFAULT_FONT_SIZE);
        return;
      }
      const anchorNode = selection.anchor.getNode();
      const element =
        anchorNode.getKey() === "root" ? anchorNode : anchorNode.getTopLevelElementOrThrow();
      const elementType = element.getType();
      const elementFormat = $isElementNode(element)
        ? (element.getFormatType() as Alignment)
        : "left";
      const tableCellParent = $findMatchingParent(anchorNode, (node) => $isTableCellNode(node));
      setIsInTable(Boolean(tableCellParent));

      if (elementType === "paragraph") {
        setBlockType("paragraph");
      } else if ($isHeadingNode(element)) {
        const tag = element.getTag();
        if (tag === "h1" || tag === "h2" || tag === "h3") {
          setBlockType(tag);
        }
      } else if ($isQuoteNode(element)) {
        setBlockType("quote");
      } else if (elementType === "code") {
        setBlockType("code");
      }

      setAlignment(elementFormat || "left");
      setIsUnderline(selection.hasFormat("underline"));
      setIsBold(selection.hasFormat("bold"));
      setIsItalic(selection.hasFormat("italic"));
      setIsCodeBlock(elementType === "code");
      if ($isListNode(element)) {
        const type = element.getListType();
        if (type === "number") {
          setListType("number");
        } else if (type === "bullet") {
          setListType("bullet");
        } else if (type === "check") {
          setListType("check");
        } else {
          setListType("none");
        }
      } else {
        setListType("none");
      }

      let derivedFontSize: string | null = null;
      if (!selection.isCollapsed()) {
        const firstTextNode = selection.getNodes().find($isTextNode);
        if (firstTextNode) {
          derivedFontSize = extractFontSize(firstTextNode.getStyle());
        }
      }
      if (!derivedFontSize) {
        derivedFontSize = extractFontSize(selection.style);
      }
      setFontSize(derivedFontSize ?? DEFAULT_FONT_SIZE);
    });
  }, [editor]);

  useEffect(() => {
    if (readOnly) {
      return;
    }
    return mergeRegisters(
      editor.registerCommand(
        SELECTION_CHANGE_COMMAND,
        () => {
          updateToolbar();
          return false;
        },
        COMMAND_PRIORITY_LOW
      ),
      editor.registerCommand(
        CAN_UNDO_COMMAND,
        (payload: boolean) => {
          setCanUndo(payload);
          return false;
        },
        COMMAND_PRIORITY_LOW
      ),
      editor.registerCommand(
        CAN_REDO_COMMAND,
        (payload: boolean) => {
          setCanRedo(payload);
          return false;
        },
        COMMAND_PRIORITY_LOW
      ),
      editor.registerUpdateListener(() => {
        updateToolbar();
      })
    );
  }, [editor, readOnly, updateToolbar]);

  const applyBlockType = (value: BlockType) => {
    setBlockType(value);
    editor.update(() => {
      const selection = $getSelection();
      if (!$isRangeSelection(selection)) {
        return;
      }
      switch (value) {
        case "paragraph":
          $setBlocksType(selection, () => $createParagraphNode());
          break;
        case "code":
          $setBlocksType(selection, () => $createCodeNode());
          break;
        case "quote":
          $setBlocksType(selection, () => $createQuoteNode());
          break;
        default:
          $setBlocksType(selection, () => $createHeadingNode(value));
          break;
      }
    });
  };

  const applyFontSize = (size: string) => {
    setFontSize(size);
    editor.update(() => {
      const selection = $getSelection();
      if (!$isRangeSelection(selection)) {
        return;
      }
      $patchStyleText(selection, { "font-size": size });
      selection.setStyle(replaceFontSizeInStyle(selection.style, size));
    });
  };

  const toggleUnderline = () => {
    editor.dispatchCommand(FORMAT_TEXT_COMMAND, "underline");
  };

  const toggleBold = () => {
    editor.dispatchCommand(FORMAT_TEXT_COMMAND, "bold");
  };

  const toggleItalic = () => {
    editor.dispatchCommand(FORMAT_TEXT_COMMAND, "italic");
  };

  const toggleCodeBlock = () => {
    applyBlockType(isCodeBlock ? "paragraph" : "code");
  };

  const toggleList = (type: Extract<ListType, "bullet" | "number" | "check">) => {
    if (listType === type) {
      editor.dispatchCommand(REMOVE_LIST_COMMAND, undefined);
      return;
    }
    editor.dispatchCommand(
      type === "bullet"
        ? INSERT_UNORDERED_LIST_COMMAND
        : type === "number"
          ? INSERT_ORDERED_LIST_COMMAND
          : INSERT_CHECK_LIST_COMMAND,
      undefined
    );
  };

  const indentSelection = () => {
    editor.dispatchCommand(INDENT_CONTENT_COMMAND, undefined);
  };

  const outdentSelection = () => {
    editor.dispatchCommand(OUTDENT_CONTENT_COMMAND, undefined);
  };

  const insertLink = useCallback(() => {
    const savedSelection = cloneCurrentSelection();
    const previousUrl = window.prompt(t("editor.promptUrl"), "https://");
    if (previousUrl === null) {
      return;
    }
    const trimmed = previousUrl.trim();
    editor.update(() => {
      if (savedSelection) {
        $setSelection(savedSelection);
      }
      editor.dispatchCommand(TOGGLE_LINK_COMMAND, trimmed || null);
    });
  }, [editor, cloneCurrentSelection, t]);

  const applyAlignment = (value: Alignment) => {
    setAlignment(value);
    editor.dispatchCommand(FORMAT_ELEMENT_COMMAND, value);
  };

  const insertHorizontalRule = useCallback(() => {
    const savedSelection = cloneCurrentSelection();
    editor.dispatchCommand(INSERT_HORIZONTAL_RULE_COMMAND, undefined);
    if (savedSelection) {
      editor.update(() => {
        $setSelection(savedSelection);
      });
    }
  }, [editor, cloneCurrentSelection]);

  const uploadImageFiles = useCallback(
    async (files: FileList | File[]) => {
      const images = Array.from(files).filter((file) => file.type.startsWith("image/"));
      if (!images.length) {
        toast.error(t("editor.errorImageOnly"));
        return;
      }
      setIsImageUploading(true);
      try {
        for (const file of images) {
          try {
            const response = await uploadAttachment(file);
            insertImageNode(editor, { src: response.url, altText: file.name });
          } catch (error) {
            console.error(error);
            toast.error(t("editor.errorUpload", { fileName: file.name }));
          }
        }
      } finally {
        setIsImageUploading(false);
      }
    },
    [editor, t]
  );

  const handleImageInputChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      const { files } = event.target;
      event.target.value = "";
      if (!files || files.length === 0) {
        return;
      }
      void uploadImageFiles(files);
    },
    [uploadImageFiles]
  );

  const triggerImagePicker = useCallback(() => {
    fileInputRef.current?.click();
  }, [fileInputRef]);

  const insertTable = useCallback(() => {
    const rows = Math.max(1, Number(window.prompt(t("editor.promptRows"), "2")) || 2);
    const columns = Math.max(1, Number(window.prompt(t("editor.promptColumns"), "2")) || 2);
    editor.dispatchCommand(INSERT_TABLE_COMMAND, {
      rows: String(rows),
      columns: String(columns),
      includeHeaders: true,
    });
  }, [editor, t]);

  const insertYoutube = useCallback(() => {
    const url = window.prompt(t("editor.promptYoutubeUrl"));
    if (!url) {
      return;
    }
    const videoId = extractYouTubeId(url);
    if (!videoId) {
      window.alert(t("editor.errorYoutubeUrl"));
      return;
    }
    const html = `
      <div class="my-4 overflow-hidden rounded-xl border bg-black aspect-video">
        <iframe
          src="https://www.youtube.com/embed/${videoId}"
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
          allowfullscreen
          class="h-full w-full border-0"
        ></iframe>
      </div>`;
    insertEmbedNode(editor, { html });
  }, [editor, t]);

  const requireTableSelection = useCallback(
    (operation: () => void) => {
      editor.update(() => {
        const selection = $getSelection();
        if (!$isRangeSelection(selection)) {
          toast.error(t("editor.errorTableCursor"));
          return;
        }
        const anchorNode = selection.anchor.getNode();
        const cellNode = $findMatchingParent(anchorNode, (node) => $isTableCellNode(node));
        if (!cellNode) {
          toast.error(t("editor.errorTableCursor"));
          return;
        }
        operation();
      });
    },
    [editor, t]
  );

  const insertTableRow = (position: "above" | "below") => {
    requireTableSelection(() => {
      const inserted = $insertTableRowAtSelection(position === "below");
      if (!inserted) {
        toast.error(t("editor.errorInsertRow"));
      }
    });
  };

  const insertTableColumn = (position: "left" | "right") => {
    requireTableSelection(() => {
      const inserted = $insertTableColumnAtSelection(position === "right");
      if (!inserted) {
        toast.error(t("editor.errorInsertColumn"));
      }
    });
  };

  const deleteTableRow = () => {
    requireTableSelection(() => {
      $deleteTableRowAtSelection();
    });
  };

  const deleteTableColumn = () => {
    requireTableSelection(() => {
      $deleteTableColumnAtSelection();
    });
  };

  const insertOptions = useMemo(
    () => [
      { label: t("editor.horizontalRule"), action: insertHorizontalRule },
      { label: t("editor.image"), action: triggerImagePicker, disabled: isImageUploading },
      { label: t("editor.table"), action: insertTable },
      { label: t("editor.youtubeEmbed"), action: insertYoutube },
    ],
    [t, insertHorizontalRule, insertTable, insertYoutube, triggerImagePicker, isImageUploading]
  );

  if (readOnly) {
    return null;
  }

  return (
    <div className="flex flex-col gap-2 px-3 py-2">
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        multiple
        className="hidden"
        onChange={handleImageInputChange}
      />
      <div className="flex flex-wrap items-center gap-2 lg:hidden">
        <Select value={blockType} onValueChange={(value: BlockType) => applyBlockType(value)}>
          <SelectTrigger className="w-36">
            <SelectValue placeholder={t("editor.textStyle")} />
          </SelectTrigger>
          <SelectContent>
            {blockOptions.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="flex items-center gap-1">
          <Button
            type="button"
            size="icon"
            variant={isBold ? "secondary" : "ghost"}
            aria-label={t("editor.bold")}
            onClick={toggleBold}
          >
            <Bold className="h-4 w-4" />
          </Button>
          <Button
            type="button"
            size="icon"
            variant={isItalic ? "secondary" : "ghost"}
            aria-label={t("editor.italic")}
            onClick={toggleItalic}
          >
            <Italic className="h-4 w-4" />
          </Button>
        </div>
        <EditorMobileOverflowMenu
          fontSize={fontSize}
          applyFontSize={applyFontSize}
          isUnderline={isUnderline}
          toggleUnderline={toggleUnderline}
          isCodeBlock={isCodeBlock}
          toggleCodeBlock={toggleCodeBlock}
          listType={listType}
          toggleList={toggleList}
          indentSelection={indentSelection}
          outdentSelection={outdentSelection}
          insertLink={insertLink}
          alignment={alignment}
          applyAlignment={applyAlignment}
          insertOptions={insertOptions}
          isInTable={isInTable}
          insertTableRow={insertTableRow}
          insertTableColumn={insertTableColumn}
          deleteTableRow={deleteTableRow}
          deleteTableColumn={deleteTableColumn}
          canUndo={canUndo}
          canRedo={canRedo}
        />
      </div>
      <div className="hidden flex-wrap items-center gap-2 lg:flex">
        {/* eslint-disable i18next/no-literal-string */}
        <div className="flex items-center gap-1">
          <Button
            type="button"
            size="icon"
            variant="ghost"
            aria-label={t("editor.undo")}
            disabled={!canUndo}
            onClick={() => editor.dispatchCommand(UNDO_COMMAND, undefined)}
          >
            ↺
          </Button>
          <Button
            type="button"
            size="icon"
            variant="ghost"
            aria-label={t("editor.redo")}
            disabled={!canRedo}
            onClick={() => editor.dispatchCommand(REDO_COMMAND, undefined)}
          >
            ↻
          </Button>
        </div>
        {/* eslint-enable i18next/no-literal-string */}
        <Select value={blockType} onValueChange={(value: BlockType) => applyBlockType(value)}>
          <SelectTrigger className="w-36">
            <SelectValue placeholder={t("editor.textStyle")} />
          </SelectTrigger>
          <SelectContent>
            {blockOptions.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={fontSize} onValueChange={(value) => applyFontSize(value)}>
          <SelectTrigger className="w-28">
            <SelectValue placeholder={t("editor.fontSize")} />
          </SelectTrigger>
          <SelectContent>
            {FONT_SIZE_OPTIONS.map((size) => (
              <SelectItem key={size} value={size}>
                {size}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button
          type="button"
          size="icon"
          variant={isBold ? "secondary" : "ghost"}
          aria-label={t("editor.bold")}
          onClick={toggleBold}
        >
          <Bold className="h-4 w-4" />
        </Button>
        <Button
          type="button"
          size="icon"
          variant={isItalic ? "secondary" : "ghost"}
          aria-label={t("editor.italic")}
          onClick={toggleItalic}
        >
          <Italic className="h-4 w-4" />
        </Button>
        <Button
          type="button"
          size="icon"
          variant={isUnderline ? "secondary" : "ghost"}
          aria-label={t("editor.underline")}
          onClick={toggleUnderline}
        >
          <span className="font-semibold underline">U</span>
        </Button>
        <Button
          type="button"
          size="icon"
          variant={isCodeBlock ? "secondary" : "ghost"}
          aria-label={t("editor.codeBlock")}
          onClick={toggleCodeBlock}
        >
          <Code2 className="h-4 w-4" />
        </Button>
        <Button
          type="button"
          size="icon"
          variant={listType === "bullet" ? "secondary" : "ghost"}
          aria-label={t("editor.bulletedList")}
          onClick={() => toggleList("bullet")}
        >
          <List className="h-4 w-4" />
        </Button>
        <Button
          type="button"
          size="icon"
          variant={listType === "number" ? "secondary" : "ghost"}
          aria-label={t("editor.numberedList")}
          onClick={() => toggleList("number")}
        >
          <ListOrdered className="h-4 w-4" />
        </Button>
        <Button
          type="button"
          size="icon"
          variant={listType === "check" ? "secondary" : "ghost"}
          aria-label={t("editor.checklist")}
          onClick={() => toggleList("check")}
        >
          <ListChecks className="h-4 w-4" />
        </Button>
        <Button
          type="button"
          size="icon"
          variant="ghost"
          aria-label={t("editor.indent")}
          onClick={indentSelection}
        >
          <IndentIncrease className="h-4 w-4" />
        </Button>
        <Button
          type="button"
          size="icon"
          variant="ghost"
          aria-label={t("editor.outdent")}
          onClick={outdentSelection}
        >
          <IndentDecrease className="h-4 w-4" />
        </Button>
        <Button
          type="button"
          size="icon"
          variant="ghost"
          aria-label={t("editor.insertLink")}
          onClick={insertLink}
        >
          <LinkIcon className="h-4 w-4" />
        </Button>
        <Select value={alignment} onValueChange={(value: Alignment) => applyAlignment(value)}>
          <SelectTrigger className="w-32">
            <SelectValue placeholder={t("editor.alignment")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="left">
              <div className="flex items-center gap-2">
                <AlignLeft className="h-4 w-4" />
                {t("editor.alignLeft")}
              </div>
            </SelectItem>
            <SelectItem value="center">
              <div className="flex items-center gap-2">
                <AlignCenter className="h-4 w-4" />
                {t("editor.alignCenter")}
              </div>
            </SelectItem>
            <SelectItem value="right">
              <div className="flex items-center gap-2">
                <AlignRight className="h-4 w-4" />
                {t("editor.alignRight")}
              </div>
            </SelectItem>
            <SelectItem value="justify">
              <div className="flex items-center gap-2">
                <AlignJustify className="h-4 w-4" />
                {t("editor.alignJustify")}
              </div>
            </SelectItem>
          </SelectContent>
        </Select>
        <EditorInsertMenu insertOptions={insertOptions} />
        <EditorTableMenu
          isInTable={isInTable}
          insertTableRow={insertTableRow}
          insertTableColumn={insertTableColumn}
          deleteTableRow={deleteTableRow}
          deleteTableColumn={deleteTableColumn}
        />
      </div>
    </div>
  );
};
