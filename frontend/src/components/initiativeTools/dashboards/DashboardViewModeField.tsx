/**
 * "Run dashboard as": each viewer's own access, or one view for everyone.
 *
 * Sits inline in the dashboard's Details form and saves on change. "Initiative"
 * runs the widgets with the access of whoever picked it, so it never shows more
 * than they can see themselves.
 */

import { useTranslation } from "react-i18next";

import type { DashboardRead } from "@/api/generated/initiativeAPI.schemas";
import { DashboardViewMode } from "@/api/generated/initiativeAPI.schemas";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useSetDashboardViewMode } from "@/hooks/useDashboards";

export function DashboardViewModeField({ dashboard }: { dashboard: DashboardRead }) {
  const { t } = useTranslation("dashboards");
  const setMode = useSetDashboardViewMode(dashboard.id);
  const mode =
    dashboard.view_as_user_id == null ? DashboardViewMode.viewer : DashboardViewMode.owner;
  const canEdit = dashboard.can.edit;

  return (
    <div className="space-y-2">
      <Label htmlFor="dashboard-view-mode">{t("viewMode.label")}</Label>
      <Select
        value={mode}
        onValueChange={(next) => setMode.mutate(next as DashboardViewMode)}
        disabled={!canEdit || setMode.isPending}
      >
        <SelectTrigger id="dashboard-view-mode">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={DashboardViewMode.viewer}>{t("viewMode.viewer")}</SelectItem>
          <SelectItem value={DashboardViewMode.owner}>{t("viewMode.owner")}</SelectItem>
        </SelectContent>
      </Select>
      <p
        className={
          mode === DashboardViewMode.owner
            ? "text-amber-700 text-xs dark:text-amber-400"
            : "text-muted-foreground text-xs"
        }
      >
        {mode === DashboardViewMode.owner ? t("viewMode.ownerHint") : t("viewMode.viewerHint")}
      </p>
      {mode === DashboardViewMode.owner && !dashboard.view_as_active && (
        <p className="text-destructive text-xs">{t("viewMode.inactive")}</p>
      )}
    </div>
  );
}
