import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ExportButton } from "@/components/exports/ExportButton";
import { TOOL_EXPORT_FORMATS } from "@/components/exports/formats";
import { exportFilenameStem } from "@/lib/exportDownload";
import { toolExportEndpoint, toolExportIdsParam, toolRouteSegment } from "@/lib/tools";

interface BulkExportButtonProps {
  /** The canonical tool — endpoint, selector param, and formats all derive
   * from the registry, so a bulk-export surface can't drift per page. */
  tool: Tool;
  /** The selected entity ids. */
  ids: number[];
}

/** Bulk-selection export for a tool's list page: one artifact per selected
 * entity in the chosen format, delivered as a zip (a selection of one stays a
 * plain file). Documents don't use this — their format set depends on the
 * selected documents' types (see DocumentsBulkBar). */
export function BulkExportButton({ tool, ids }: BulkExportButtonProps) {
  const formats = TOOL_EXPORT_FORMATS[tool];
  if (!formats || ids.length === 0) {
    return null;
  }
  return (
    <ExportButton
      endpoint={toolExportEndpoint(tool)}
      params={{ [toolExportIdsParam(tool)]: ids }}
      formats={formats}
      filenameStem={exportFilenameStem(toolRouteSegment(tool), toolRouteSegment(tool))}
    />
  );
}
