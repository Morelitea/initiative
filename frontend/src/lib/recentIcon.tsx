import type { ReactNode } from "react";

import type { RecentItemRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { getDocumentIcon, getDocumentIconColor } from "@/lib/fileUtils";
import { TOOL_REGISTRY } from "@/lib/tools";
import { cn } from "@/lib/utils";

/**
 * Render the entity-specific icon for a recent item in the layout tabs bar.
 *
 * - Projects show the emoji icon set on the project itself.
 * - Documents resolve to the same icon + color used in document lists
 *   (via ``getDocumentIcon`` / ``getDocumentIconColor``).
 * - Every other tool renders its registry icon.
 */
export function renderRecentIcon(item: RecentItemRead): ReactNode {
  switch (item.entity_type) {
    case "project": {
      if (!item.icon) return null;
      return <span className="text-base leading-none">{item.icon}</span>;
    }
    case "document": {
      const Icon = getDocumentIcon(item.document_type, item.mime_type, item.original_filename);
      const color = getDocumentIconColor(
        item.document_type,
        item.mime_type,
        item.original_filename
      );
      return <Icon className={cn("h-4 w-4", color)} />;
    }
    default: {
      const Icon = TOOL_REGISTRY[item.entity_type as Tool]?.icon;
      return Icon ? <Icon className="h-4 w-4 text-muted-foreground" /> : null;
    }
  }
}
