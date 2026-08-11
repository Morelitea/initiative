import { Link, useParams } from "@tanstack/react-router";
import { LayoutDashboard, Loader2, SearchX, ShieldAlert } from "lucide-react";
import { useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";

import { StatusMessage } from "@/components/StatusMessage";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useDashboard } from "@/hooks/useDashboards";
import { useInitiatives } from "@/hooks/useInitiatives";
import { useRecordRecentView } from "@/hooks/useRecents";
import { getHttpStatus } from "@/lib/errorMessage";
import { useGuildPath } from "@/lib/guildUrl";

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

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <LayoutDashboard className="h-5 w-5 text-muted-foreground" />
            {t("canvasPending")}
          </CardTitle>
          <CardDescription>{t("canvasPendingDescription")}</CardDescription>
        </CardHeader>
      </Card>
    </div>
  );
}
