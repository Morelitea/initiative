import { GalleryHorizontalEnd, Gauge } from "lucide-react";
import type { ReactNode } from "react";

import type { RecentItemRead } from "@/api/generated/initiativeAPI.schemas";
import { getDocumentIcon, getDocumentIconColor } from "@/lib/fileUtils";
import { cn } from "@/lib/utils";

/**
 * Render the entity-specific icon for a recent item in the layout tabs bar.
 *
 * - Projects show the emoji icon set on the project itself.
 * - Documents resolve to the same icon + color used in document lists
 *   (via ``getDocumentIcon`` / ``getDocumentIconColor``).
 * - Queues use ``GalleryHorizontalEnd``; counter groups use ``Gauge``.
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
    case "queue":
      return <GalleryHorizontalEnd className="h-4 w-4 text-muted-foreground" />;
    case "counter_group":
      return <Gauge className="h-4 w-4 text-muted-foreground" />;
    default:
      return null;
  }
}
