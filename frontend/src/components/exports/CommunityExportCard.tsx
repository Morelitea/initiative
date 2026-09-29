import { Download, FileDown } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  getReadGuildExportStatusApiV1CGuildIdExportsCommunityStatusGetQueryKey,
  useReadGuildExportStatusApiV1CGuildIdExportsCommunityStatusGet,
} from "@/api/generated/exports/exports";
import type { ExportJobRead } from "@/api/generated/initiativeAPI.schemas";
import { ExportWizard } from "@/components/exports/ExportWizard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { RelativeTime } from "@/components/ui/relative-time";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useGuilds } from "@/hooks/useGuilds";
import { downloadExportArtifact } from "@/lib/exportDownload";
import { queryClient } from "@/lib/queryClient";

const ACTIVE = new Set(["queued", "running"]);
const POLL_MS = 5000;

const STATUS_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  done: "default",
  queued: "secondary",
  running: "secondary",
  failed: "destructive",
  expired: "outline",
};

/** Effective status at render time: polling stops once the job is terminal,
 * so a page left open can hold a stale "done" whose artifact has since been
 * cleaned up. Mirrors the clamp the jobs table makes. */
function displayStatus(job: ExportJobRead): string {
  if (
    job.status === "done" &&
    job.expires_at != null &&
    new Date(job.expires_at).getTime() <= Date.now()
  ) {
    return "expired";
  }
  return job.status;
}

/** Settings → Data: the community's own export, and the state of the last
 * one. A community takes one of these at a time and rarely, so the card says
 * who took it and how it ended rather than leaving the next person to find
 * out by being refused. */
export function CommunityExportCard() {
  const { t } = useTranslation("exports");
  const guildId = useActiveGuildId();
  const { activeGuild } = useGuilds();
  const [wizardOpen, setWizardOpen] = useState(false);

  // Taking the whole community out in one file is the seat's errand, which
  // the server checks on request and again when the job renders. The card
  // says the same thing, rather than resting on which tab it happens to sit
  // in.
  const heldBySeat = Boolean(activeGuild?.can.seat);

  const statusQuery = useReadGuildExportStatusApiV1CGuildIdExportsCommunityStatusGet(guildId, {
    query: {
      refetchInterval: (query) =>
        ACTIVE.has(query.state.data?.latest?.status ?? "") ? POLL_MS : false,
    },
  });
  const status = statusQuery.data;
  const latest = status?.latest ?? null;
  const jobStatus = latest ? displayStatus(latest) : null;
  const downloadable = jobStatus === "done" && !latest?.delivered;
  const availableAt = status?.next_available_at ?? null;
  const waiting = availableAt != null && new Date(availableAt).getTime() > Date.now();

  // The wizard starts the job; reopening the question is how the card learns
  // about it (and then polls itself while it runs).
  const closeWizard = (open: boolean) => {
    setWizardOpen(open);
    if (!open) {
      void queryClient.invalidateQueries({
        queryKey: getReadGuildExportStatusApiV1CGuildIdExportsCommunityStatusGetQueryKey(guildId),
      });
    }
  };

  if (!heldBySeat) {
    return null;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("entry.guildTitle")}</CardTitle>
        <CardDescription>{t("entry.guildDescription")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {status != null && (
          <div className="space-y-2 rounded-lg border p-3">
            <p className="font-medium text-sm">{t("community.lastExport")}</p>
            {latest == null || jobStatus == null ? (
              <p className="text-muted-foreground text-sm">{t("community.none")}</p>
            ) : (
              <>
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
                  <Badge variant={STATUS_VARIANT[jobStatus] ?? "secondary"}>
                    {t(`table.status.${jobStatus}` as never, { defaultValue: jobStatus })}
                  </Badge>
                  <span className="text-muted-foreground">
                    {status.latest_started_by
                      ? t("community.startedBy", { name: status.latest_started_by })
                      : t("community.startedByUnknown")}
                  </span>
                  <RelativeTime className="text-muted-foreground" date={latest.created_at} />
                </div>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                  {downloadable && (
                    <>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() =>
                          void downloadExportArtifact(
                            guildId,
                            latest.id,
                            t as (key: string, options?: Record<string, unknown>) => string,
                            latest.source,
                            latest.format
                          )
                        }
                      >
                        <Download className="h-4 w-4" />
                        {t("table.download")}
                      </Button>
                      {latest.expires_at != null && (
                        <span className="text-muted-foreground text-xs">
                          {t("community.expires")}{" "}
                          <RelativeTime date={latest.expires_at} showTitle={false} />
                        </span>
                      )}
                    </>
                  )}
                  {latest.delivered && (
                    <span className="text-muted-foreground text-xs">
                      {t("community.delivered")}
                    </span>
                  )}
                  {jobStatus === "expired" && (
                    <span className="text-muted-foreground text-xs">
                      {t("community.expiredNote")}
                    </span>
                  )}
                  {jobStatus === "failed" && (
                    <span className="text-muted-foreground text-xs">
                      {t("community.failedNote")}
                    </span>
                  )}
                  {ACTIVE.has(jobStatus) && (
                    <span className="text-muted-foreground text-xs">
                      {t("community.preparing")}
                    </span>
                  )}
                </div>
              </>
            )}
          </div>
        )}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <Button onClick={() => setWizardOpen(true)} disabled={waiting}>
            <FileDown className="h-4 w-4" />
            {t("entry.open")}
          </Button>
          {waiting && (
            <span className="text-muted-foreground text-sm">
              {t("community.nextAvailable")} <RelativeTime date={availableAt} showTitle={false} />
            </span>
          )}
        </div>
      </CardContent>
      {/* Mounted outside the open check so a job started here keeps polling
          (and delivers its download) after the dialog closes. */}
      <ExportWizard scope="guild" open={wizardOpen} onOpenChange={closeWizard} />
    </Card>
  );
}
