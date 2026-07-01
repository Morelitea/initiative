import { Shield } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

interface BulkAccessBarProps {
  count: number;
  /** Whether the current user can manage sharing on every selected item. */
  canManage: boolean;
  onEditAccess: () => void;
  onExit: () => void;
}

/**
 * The toolbar shown above a list while items are selected — a count and an
 * "Edit access" action. Mirrors the documents bulk toolbar so every list feels
 * the same.
 */
export function BulkAccessBar({ count, canManage, onEditAccess, onExit }: BulkAccessBarProps) {
  const { t } = useTranslation(["access", "common"]);

  return (
    <div className="flex items-center justify-between rounded-md border border-primary bg-primary/5 p-4">
      <div className="font-medium text-sm">{t("bulkBar.selected", { count })}</div>
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={onEditAccess}
          disabled={count === 0 || !canManage}
          title={canManage ? undefined : t("bulkBar.needManage")}
        >
          <Shield className="h-4 w-4" />
          {t("bulkBar.editAccess")}
        </Button>
        <Button variant="ghost" size="sm" onClick={onExit}>
          {t("common:cancel")}
        </Button>
      </div>
    </div>
  );
}

/** Selected items can have their sharing managed only by an owner/editor. */
export function canManageSharing(items: { my_permission_level?: string | null }[]): boolean {
  return (
    items.length > 0 &&
    items.every((i) => i.my_permission_level === "write" || i.my_permission_level === "owner")
  );
}
