import { Link, useParams } from "@tanstack/react-router";
import { SearchX, Settings, ShieldAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { DashboardCanvas } from "@/components/initiativeTools/dashboards/DashboardCanvas";
import { DashboardUpdateBadge } from "@/components/initiativeTools/dashboards/DashboardUpdateBadge";
import { WidgetConfigDialog } from "@/components/initiativeTools/dashboards/WidgetConfigDialog";
import { WidgetPicker } from "@/components/initiativeTools/dashboards/WidgetPicker";
import { StatusMessage } from "@/components/StatusMessage";
import { ToolBreadcrumb } from "@/components/tools/ToolBreadcrumb";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useDashboardEditor } from "@/hooks/useDashboardEditor";
import { useDashboard, useWidgetCatalog } from "@/hooks/useDashboards";
import { useRecordRecentView } from "@/hooks/useRecents";
import { getHttpStatus } from "@/lib/errorMessage";
import { useGuildPath } from "@/lib/guildUrl";
import { hasWriteAccess } from "@/lib/permissions";
import { toolListRoute, toolSettingsRoute } from "@/lib/tools";

export function DashboardDetailPage() {
  const { t } = useTranslation(["dashboards", "common"]);
  const {
    guildId,
    dashboardId,
    initiativeId: initiativeIdParam,
  } = useParams({ strict: false }) as {
    guildId: string;
    dashboardId: string;
    initiativeId?: string;
  };
  // The initiative comes from the path so the back-links still work when the
  // entity itself failed to load.
  const initiativeId = initiativeIdParam ? Number(initiativeIdParam) : null;
  const parsedId = Number(dashboardId);
  const gp = useGuildPath();

  const dashboardQuery = useDashboard(Number.isFinite(parsedId) ? parsedId : null);
  const dashboard = dashboardQuery.data;

  // Track recently viewed dashboards for the layout header tabs bar — only
  // once the read succeeds (access checks passed).
  const recordViewMutation = useRecordRecentView("dashboard", Number(guildId));
  const viewedDashboardId = dashboard?.id;
  useEffect(() => {
    if (!viewedDashboardId) return;
    recordViewMutation.mutate(viewedDashboardId);
  }, [viewedDashboardId, recordViewMutation.mutate]);

  const catalogQuery = useWidgetCatalog();
  // Arranging and binding are authoring — they write the dashboard's own row —
  // so the canvas is static without DAC write rather than merely looking it.
  const canEdit = hasWriteAccess(dashboard?.my_permission_level);
  const editor = useDashboardEditor(dashboard, catalogQuery.data, canEdit);
  const [configuringId, setConfiguringId] = useState<string | null>(null);
  const configuring =
    editor.definition.widgets.find((widget) => widget.id === configuringId) ?? null;

  if (!Number.isFinite(parsedId)) {
    return <p className="text-destructive">{t("notFound")}</p>;
  }

  if (dashboardQuery.isError) {
    const status = getHttpStatus(dashboardQuery.error);
    const backTo = gp(toolListRoute(Tool.dashboard, initiativeId));
    const backLabel = t("backToDashboards");

    if (status === 403) {
      return (
        <StatusMessage
          icon={<ShieldAlert />}
          title={t("noAccess")}
          description={t("noAccessDescription")}
          backTo={backTo}
          backLabel={backLabel}
        />
      );
    }
    return (
      <StatusMessage
        icon={<SearchX />}
        title={t("notFound")}
        description={t("notFoundDescription")}
        backTo={backTo}
        backLabel={backLabel}
      />
    );
  }

  // The page frame is correct as soon as the route resolves; only the canvas is
  // waiting on anything. Replacing the whole page with a spinner would throw the
  // breadcrumb, title, and toolbar away and rebuild them a moment later, which
  // is what made an ordinary load look like a reload.
  return (
    <div className="space-y-6">
      <ToolBreadcrumb
        tool={Tool.dashboard}
        initiativeId={dashboard?.initiative_id}
        trail={[{ label: dashboard ? dashboard.name : <Skeleton className="h-4 w-32" /> }]}
      />

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          {dashboard ? (
            <h1 className="font-semibold text-3xl tracking-tight">{dashboard.name}</h1>
          ) : (
            <Skeleton className="h-9 w-64" />
          )}
          {dashboard?.description && (
            <p className="text-muted-foreground text-sm">{dashboard.description}</p>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {dashboard && <DashboardUpdateBadge dashboard={dashboard} canEdit={canEdit} />}
          {canEdit && (
            <>
              {editor.isSaving && (
                <span className="text-muted-foreground text-xs">{t("canvas.saving")}</span>
              )}
              <WidgetPicker
                catalog={catalogQuery.data}
                widgetCount={editor.definition.widgets.length}
                onAdd={editor.addWidget}
              />
              {dashboard && (
                <Button variant="outline" size="sm" asChild>
                  <Link
                    to={gp(toolSettingsRoute(Tool.dashboard, initiativeId, dashboard.id))}
                    className="inline-flex items-center gap-2"
                  >
                    <Settings className="h-4 w-4" />
                    {t("common:toolSettings.title")}
                  </Link>
                </Button>
              )}
            </>
          )}
        </div>
      </div>

      <DashboardCanvas
        definition={editor.definition}
        config={editor.config}
        catalog={catalogQuery.data}
        initiativeId={dashboard?.initiative_id}
        dashboardId={dashboard?.id}
        canEdit={canEdit}
        isLoading={!dashboard}
        onLayoutChange={editor.replaceDefinition}
        onConfigureWidget={setConfiguringId}
        onRemoveWidget={editor.removeWidget}
      />

      {dashboard != null && (
        <WidgetConfigDialog
          widget={configuring}
          catalog={catalogQuery.data}
          initiativeId={dashboard.initiative_id}
          dashboardId={dashboard.id}
          open={configuring !== null}
          onOpenChange={(next) => !next && setConfiguringId(null)}
          onSave={(patch) => configuringId && editor.updateWidget(configuringId, patch)}
        />
      )}
    </div>
  );
}
