import { Link, useParams } from "@tanstack/react-router";
import { SearchX, ShieldAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { DashboardCanvas } from "@/components/initiativeTools/dashboards/DashboardCanvas";
import { DashboardUpdateBadge } from "@/components/initiativeTools/dashboards/DashboardUpdateBadge";
import { WidgetConfigDialog } from "@/components/initiativeTools/dashboards/WidgetConfigDialog";
import { WidgetPicker } from "@/components/initiativeTools/dashboards/WidgetPicker";
import { StatusMessage } from "@/components/StatusMessage";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Skeleton } from "@/components/ui/skeleton";
import { useDashboardEditor } from "@/hooks/useDashboardEditor";
import { useDashboard, useWidgetCatalog } from "@/hooks/useDashboards";
import { useInitiatives } from "@/hooks/useInitiatives";
import { useRecordRecentView } from "@/hooks/useRecents";
import { getHttpStatus } from "@/lib/errorMessage";
import { useGuildPath } from "@/lib/guildUrl";
import { hasWriteAccess } from "@/lib/permissions";

export function DashboardDetailPage() {
  const { t } = useTranslation(["dashboards", "common"]);
  const { guildId, dashboardId } = useParams({ strict: false }) as {
    guildId: string;
    dashboardId: string;
  };
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

  const initiativesQuery = useInitiatives();
  const initiativeName = useMemo(
    () =>
      dashboard
        ? (initiativesQuery.data?.find((init) => init.id === dashboard.initiative_id)?.name ?? null)
        : null,
    [dashboard, initiativesQuery.data]
  );

  if (!Number.isFinite(parsedId)) {
    return <p className="text-destructive">{t("notFound")}</p>;
  }

  if (dashboardQuery.isError) {
    const status = getHttpStatus(dashboardQuery.error);
    const backTo = gp("/dashboards");
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
      <Breadcrumb>
        <BreadcrumbList>
          {initiativeName && dashboard && (
            <>
              <BreadcrumbItem>
                <BreadcrumbLink asChild>
                  <Link to={gp(`/initiatives/${dashboard.initiative_id}`)}>{initiativeName}</Link>
                </BreadcrumbLink>
              </BreadcrumbItem>
              <BreadcrumbSeparator />
            </>
          )}
          <BreadcrumbItem>
            <BreadcrumbLink asChild>
              <Link to={gp("/dashboards")}>{t("title")}</Link>
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            {dashboard ? (
              <BreadcrumbPage>{dashboard.name}</BreadcrumbPage>
            ) : (
              <Skeleton className="h-4 w-32" />
            )}
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

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
            </>
          )}
        </div>
      </div>

      <DashboardCanvas
        definition={editor.definition}
        config={editor.config}
        catalog={catalogQuery.data}
        initiativeId={dashboard?.initiative_id}
        canEdit={canEdit}
        isLoading={!dashboard}
        onLayoutChange={editor.replaceDefinition}
        onConfigureWidget={setConfiguringId}
        onRemoveWidget={editor.removeWidget}
      />

      <WidgetConfigDialog
        widget={configuring}
        catalog={catalogQuery.data}
        open={configuring !== null}
        onOpenChange={(next) => !next && setConfiguringId(null)}
        onSave={(patch) => configuringId && editor.updateWidget(configuringId, patch)}
      />
    </div>
  );
}
