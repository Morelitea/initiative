import { FileDown } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ExportButton } from "@/components/exports/ExportButton";
import { TOOL_EXPORT_FORMATS } from "@/components/exports/formats";
import { Button } from "@/components/ui/button";
import { exportFilenameStem } from "@/lib/exportDownload";
import { canExportAll } from "@/lib/permissions";
import { toolExportEndpoint, toolExportIdsParam, toolRouteSegment } from "@/lib/tools";

interface BulkExportButtonProps {
  /** The canonical tool — endpoint, selector param, and formats all derive
   * from the registry, so a bulk-export surface can't drift per page. */
  tool: Tool;
  /** The selected entities, with the rung the viewer holds on each. */
  items: { id: number; my_permission_level?: string | null }[];
}

/** Bulk-selection export for a tool's list page: one artifact per selected
 * entity in the chosen format, delivered as a zip (a selection of one stays a
 * plain file). Offered only when the viewer may export every one of them — the
 * owner's rung, as deleting is — and shown disabled otherwise. Documents don't
 * use this — their format set depends on the selected documents' types (see
 * DocumentsBulkBar). */
export function BulkExportButton({ tool, items }: BulkExportButtonProps) {
  const { t } = useTranslation("exports");
  const formats = TOOL_EXPORT_FORMATS[tool];
  if (!formats || items.length === 0) {
    return null;
  }
  if (!canExportAll(items)) {
    return <BulkExportUnavailable title={t("export.ownerRequired")} />;
  }
  return (
    <ExportButton
      endpoint={toolExportEndpoint(tool)}
      params={{ [toolExportIdsParam(tool)]: items.map((item) => item.id) }}
      formats={formats}
      filenameStem={exportFilenameStem(toolRouteSegment(tool), toolRouteSegment(tool))}
    />
  );
}

/** The export button a selection cannot use, saying why. */
export function BulkExportUnavailable({ title }: { title: string }) {
  const { t } = useTranslation("exports");
  return (
    <Button variant="outline" size="sm" disabled title={title} aria-label={title}>
      <FileDown className="h-4 w-4" />
      <span className="hidden sm:inline">{t("export.button")}</span>
    </Button>
  );
}
