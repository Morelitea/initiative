import { $setBlocksType } from "@lexical/selection";
import { $createParagraphNode, $getSelection, $isRangeSelection } from "lexical";

import { useToolbarContext } from "@/components/ui/editor/context/toolbar-context";
import { useBlockTypeToBlockName } from "@/components/ui/editor/plugins/toolbar/block-format/block-format-data";
import { SelectItem } from "@/components/ui/select";

const BLOCK_FORMAT_VALUE = "paragraph";

export function FormatParagraph() {
  const blockTypeToBlockName = useBlockTypeToBlockName();
  const { activeEditor } = useToolbarContext();

  const formatParagraph = () => {
    activeEditor.update(() => {
      const selection = $getSelection();
      if ($isRangeSelection(selection)) {
        $setBlocksType(selection, () => $createParagraphNode());
      }
    });
  };

  return (
    <SelectItem value={BLOCK_FORMAT_VALUE} onPointerDown={formatParagraph}>
      <div className="flex items-center gap-1 font-normal">
        {blockTypeToBlockName[BLOCK_FORMAT_VALUE].icon}
        {blockTypeToBlockName[BLOCK_FORMAT_VALUE].label}
      </div>
    </SelectItem>
  );
}
