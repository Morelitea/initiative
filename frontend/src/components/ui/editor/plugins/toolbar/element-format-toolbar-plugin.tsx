import { useState } from "react";
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
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Separator } from "@/components/ui/separator";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";

type AlignmentType = "left" | "center" | "right" | "justify";

const ELEMENT_FORMAT_OPTIONS: {
  [key in AlignmentType]: {
    icon: React.ReactNode;
    name: string;
  };
} = {
  left: {
    icon: <AlignLeftIcon className="size-4" />,
    name: "Left Align",
  },
  center: {
    icon: <AlignCenterIcon className="size-4" />,
    name: "Center Align",
  },
  right: {
    icon: <AlignRightIcon className="size-4" />,
    name: "Right Align",
  },
  justify: {
    icon: <AlignJustifyIcon className="size-4" />,
    name: "Justify Align",
  },
} as const;

export function ElementFormatToolbarPlugin({ separator = true }: { separator?: boolean }) {
  const { activeEditor } = useToolbarContext();
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

  const handleIndent = (direction: "indent" | "outdent") => {
    if (direction === "indent") {
      activeEditor.dispatchCommand(INDENT_CONTENT_COMMAND, undefined);
    } else {
      activeEditor.dispatchCommand(OUTDENT_CONTENT_COMMAND, undefined);
    }
  };

  // Get current alignment, defaulting to "left" if not a standard alignment
  const currentAlignment: AlignmentType =
    elementFormat in ELEMENT_FORMAT_OPTIONS ? (elementFormat as AlignmentType) : "left";

  return (
    <>
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
        </DropdownMenuContent>
      </DropdownMenu>
      {separator && <Separator orientation="vertical" className="h-7!" />}
      {/* Indentation toggles */}
      <ToggleGroup
        type="single"
        onValueChange={(v) => v && handleIndent(v as "indent" | "outdent")}
      >
        <ToggleGroupItem value="outdent" aria-label="Outdent" variant={"outline"} size="sm">
          <IndentDecreaseIcon className="size-4" />
        </ToggleGroupItem>

        <ToggleGroupItem value="indent" variant={"outline"} aria-label="Indent" size="sm">
          <IndentIncreaseIcon className="size-4" />
        </ToggleGroupItem>
      </ToggleGroup>
    </>
  );
}
