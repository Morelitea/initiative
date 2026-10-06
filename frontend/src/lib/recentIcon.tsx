import type { ReactNode } from "react";

import { type RecentItemRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { documentIcon } from "@/lib/documentIcon";
import { TOOL_ICONS } from "@/lib/tools";
import { cn } from "@/lib/utils";

/**
 * Render the entity-specific icon for a recent item in the layout tabs bar.
 *
 * - Projects show the emoji icon set on the project itself.
 * - Documents resolve to the same icon + color used in document lists
 *   (via ``documentIcon``).
 * - Every other tool renders its registry icon.
 */
export function renderRecentIcon(item: RecentItemRead): ReactNode {
  switch (item.entity_type) {
    case Tool.project: {
      if (!item.icon) return null;
      return <span className="text-base leading-none">{item.icon}</span>;
    }
    case Tool.document: {
      const { Icon, colorClass } = documentIcon(item);
      return <Icon className={cn("h-4 w-4", colorClass)} />;
    }
    default: {
      const Icon = TOOL_ICONS[item.entity_type as Tool];
      return Icon ? <Icon className="h-4 w-4 text-muted-foreground" /> : null;
    }
  }
}
