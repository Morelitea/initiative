import { useState } from "react";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { BulkAccessBar, canManageSharing } from "@/components/access/BulkAccessBar";
import {
  type BulkAccessItem,
  BulkEditAccessDialog,
} from "@/components/access/BulkEditAccessDialog";
import { BulkExportButton } from "@/components/exports/BulkExportButton";

/** The slice of {@link useGridSelection} this section drives. */
interface GridSelectionLike<T> {
  active: boolean;
  selectedItems: T[];
  exit: () => void;
}

interface BulkAccessSectionProps<
  T extends BulkAccessItem & { my_permission_level?: string | null },
> {
  /** The grid selection driving this page's cards. Its state stays on the page. */
  selection: GridSelectionLike<T>;
  /** The tool being listed — routes the bulk export and access endpoints. */
  tool: Tool;
  /** Invalidate the tool's list caches after a successful access change. */
  invalidate: () => void;
}

/**
 * The bulk edit-access toolbar shared by the standalone tool-list pages (queues,
 * counter groups): the {@link BulkAccessBar} (with a bulk export action) shown
 * while items are selected, and the {@link BulkEditAccessDialog} it opens.
 * Entering selection mode is the toolbar's overflow menu's job, so this renders
 * nothing at all until something is selected.
 */
export function BulkAccessSection<
  T extends BulkAccessItem & { my_permission_level?: string | null },
>({ selection, tool, invalidate }: BulkAccessSectionProps<T>) {
  const [dialogOpen, setDialogOpen] = useState(false);

  return (
    <>
      {selection.active ? (
        <BulkAccessBar
          count={selection.selectedItems.length}
          canManage={canManageSharing(selection.selectedItems)}
          onEditAccess={() => setDialogOpen(true)}
          onExit={selection.exit}
        >
          <BulkExportButton tool={tool} ids={selection.selectedItems.map((item) => item.id)} />
        </BulkAccessBar>
      ) : null}
      <BulkEditAccessDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        items={selection.selectedItems}
        resourceType={tool}
        invalidate={invalidate}
        onSuccess={selection.exit}
      />
    </>
  );
}
