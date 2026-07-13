import { importFile } from "@lexical/file";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { UploadIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

// Export moved to the document header's engine-backed Export menu, which
// emits the same @lexical/file schema (and .lexical extension) this import
// consumes — one export surface, round-trippable. The toolbar keeps only the
// import side; the export engine has no import path.
export function ImportExportPlugin() {
  const [editor] = useLexicalComposerContext();

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant={"ghost"}
          onClick={() => importFile(editor)}
          title="Import"
          aria-label="Import editor state from JSON"
          size={"sm"}
          className="p-2"
        >
          <UploadIcon className="size-4" />
        </Button>
      </TooltipTrigger>
      <TooltipContent>Import Content</TooltipContent>
    </Tooltip>
  );
}
