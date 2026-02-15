import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { $isLinkNode } from "@lexical/link";
import { $findMatchingParent } from "@lexical/utils";
import {
  $isElementNode,
  $isRangeSelection,
  BaseSelection,
  ElementFormatType,
  FORMAT_ELEMENT_COMMAND,
  INDENT_CONTENT_COMMAND,
  OUTDENT_CONTENT_COMMAND,
} from "lexical";
import {
  AlignCenterIcon,
  AlignJustifyIcon,
  AlignLeftIcon,
  AlignRightIcon,
  ChevronDownIcon,
  IndentDecreaseIcon,
  IndentIncreaseIcon,
} from "lucide-react";

import { useToolbarContext } from "@/components/ui/editor/context/toolbar-context";
import { useUpdateToolbarHandler } from "@/components/ui/editor/editor-hooks/use-update-toolbar";
import { getSelectedNode } from "@/components/ui/editor/utils/get-selected-node";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

type AlignmentType = "left" | "center" | "right" | "justify";

export function ElementFormatToolbarPlugin() {
  const { activeEditor } = useToolbarContext();
  const { t } = useTranslation("documents");

  const ELEMENT_FORMAT_OPTIONS = useMemo(
    () => ({
      left: {
        icon: <AlignLeftIcon className="size-4" />,
        name: t("editor.leftAlign"),
      },
      center: {
        icon: <AlignCenterIcon className="size-4" />,
        name: t("editor.centerAlign"),
      },
      right: {
        icon: <AlignRightIcon className="size-4" />,
        name: t("editor.rightAlign"),
      },
      justify: {
        icon: <AlignJustifyIcon className="size-4" />,
        name: t("editor.justifyAlign"),
      },
    }),
    [t]
  );
  const [elementFormat, setElementFormat] = useState<ElementFormatType>("left");

  const $updateToolbar = (selection: BaseSelection) => {
    if ($isRangeSelection(selection)) {
      const node = getSelectedNode(selection);
      const parent = node.getParent();

      let matchingParent;
      if ($isLinkNode(parent)) {
        // If node is a link, we need to fetch the parent paragraph node to set format
        matchingParent = $findMatchingParent(
          node,
          (parentNode) => $isElementNode(parentNode) && !parentNode.isInline()
        );
      }
      setElementFormat(
        $isElementNode(matchingParent)
          ? matchingParent.getFormatType()
          : $isElementNode(node)
            ? node.getFormatType()
            : parent?.getFormatType() || "left"
      );
    }
  };

  useUpdateToolbarHandler($updateToolbar);

  const handleAlignmentChange = (value: AlignmentType) => {
    setElementFormat(value);
    activeEditor.dispatchCommand(FORMAT_ELEMENT_COMMAND, value);
  };

  // Get current alignment, defaulting to "left" if not a standard alignment
  const currentAlignment: AlignmentType =
    elementFormat in ELEMENT_FORMAT_OPTIONS ? (elementFormat as AlignmentType) : "left";

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className="h-8 gap-1 px-2">
          {ELEMENT_FORMAT_OPTIONS[currentAlignment].icon}
          <ChevronDownIcon className="size-3" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        {Object.entries(ELEMENT_FORMAT_OPTIONS).map(([value, option]) => (
          <DropdownMenuItem
            key={value}
            onClick={() => handleAlignmentChange(value as AlignmentType)}
            className={currentAlignment === value ? "bg-accent" : ""}
          >
            {option.icon}
            <span className="ml-2">{option.name}</span>
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onClick={() => activeEditor.dispatchCommand(INDENT_CONTENT_COMMAND, undefined)}
        >
          <IndentIncreaseIcon className="size-4" />
          <span className="ml-2">{t("editor.indent")}</span>
        </DropdownMenuItem>
        <DropdownMenuItem
          onClick={() => activeEditor.dispatchCommand(OUTDENT_CONTENT_COMMAND, undefined)}
        >
          <IndentDecreaseIcon className="size-4" />
          <span className="ml-2">{t("editor.outdent")}</span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
