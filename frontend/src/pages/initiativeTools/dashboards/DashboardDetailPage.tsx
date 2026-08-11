import { Link, useParams } from "@tanstack/react-router";
import { Loader2, SearchX, ShieldAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { AddWidgetMenu } from "@/components/initiativeTools/dashboards/AddWidgetMenu";
import { DashboardCanvas } from "@/components/initiativeTools/dashboards/DashboardCanvas";
import { WidgetConfigDialog } from "@/components/initiativeTools/dashboards/WidgetConfigDialog";
import { StatusMessage } from "@/components/StatusMessage";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
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

  if (dashboardQuery.isLoading) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("loadingDashboard")}
      </div>
    );
  }

  if (dashboardQuery.isError || !dashboard) {
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

  return (
    <div className="space-y-6">
      <Breadcrumb>
        <BreadcrumbList>
          {initiativeName && (
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
            <BreadcrumbPage>{dashboard.name}</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      <div className="space-y-1">
        <h1 className="font-semibold text-3xl tracking-tight">{dashboard.name}</h1>
        {dashboard.description && (
          <p className="text-muted-foreground text-sm">{dashboard.description}</p>
        )}
      </div>

      {canEdit && (
        <div className="flex items-center justify-end gap-2">
          {editor.isSaving && (
            <span className="text-muted-foreground text-xs">{t("canvas.saving")}</span>
          )}
          <AddWidgetMenu
            catalog={catalogQuery.data}
            widgetCount={editor.definition.widgets.length}
            onAdd={editor.addWidget}
          />
        </div>
      )}

      <DashboardCanvas
        definition={editor.definition}
        config={editor.config}
        catalog={catalogQuery.data}
        canEdit={canEdit}
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
