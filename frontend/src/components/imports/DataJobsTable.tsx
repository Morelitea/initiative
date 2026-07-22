import { Download, FileText, Loader2, X } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { useListExportJobsApiV1GGuildIdExportsGet } from "@/api/generated/exports/exports";
import {
  getListImportJobsApiV1GGuildIdImportsJobsGetQueryKey,
  useCancelImportJobApiV1GGuildIdImportsJobsJobIdDelete,
  useListImportJobsApiV1GGuildIdImportsJobsGet,
} from "@/api/generated/imports/imports";
import type { ExportJobRead, ImportJobRead } from "@/api/generated/initiativeAPI.schemas";
import { ImportReport } from "@/components/imports/ImportReport";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { RelativeTime } from "@/components/ui/relative-time";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { downloadExportArtifact } from "@/lib/exportDownload";
import { queryClient } from "@/lib/queryClient";

const ACTIVE = new Set(["staged", "queued", "running"]);
const POLL_MS = 5000;

const STATUS_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  done: "default",
  staged: "secondary",
  queued: "secondary",
  running: "secondary",
  failed: "destructive",
  cancelled: "outline",
  expired: "outline",
};

type Row =
  | { direction: "export"; job: ExportJobRead }
  | { direction: "import"; job: ImportJobRead };

/** Effective status at render time for export rows: polling stops once every
 * job is terminal, so a tab left open can hold a stale "done" row whose
 * artifact has since expired. Clamp it client-side. */
function exportDisplayStatus(job: ExportJobRead): string {
  if (
    job.status === "done" &&
    job.expires_at != null &&
    new Date(job.expires_at).getTime() <= Date.now()
  ) {
    return "expired";
  }
  return job.status;
}

/** One table for both directions of the Data tab: export and import jobs
 * interleaved newest-first (RLS scopes rows — members their own, guild
 * admins everyone's). Per-row actions stay direction-specific: Download for
 * finished exports, Cancel for staged/queued imports, a report view for
 * terminal imports. Polls while any job of either direction is active. */
export function DataJobsTable() {
  const { t } = useTranslation(["imports", "exports"]);
  const guildId = useActiveGuildId();
  const [reportJob, setReportJob] = useState<ImportJobRead | null>(null);

  const exportsQuery = useListExportJobsApiV1GGuildIdExportsGet(guildId, {
    query: {
      refetchInterval: (query) =>
        (query.state.data ?? []).some((job) => ACTIVE.has(job.status)) ? POLL_MS : false,
    },
  });
  const importsQuery = useListImportJobsApiV1GGuildIdImportsJobsGet(guildId, {
    query: {
      refetchInterval: (query) =>
        (query.state.data ?? []).some((job) => ACTIVE.has(job.status)) ? POLL_MS : false,
    },
  });
  const cancelMutation = useCancelImportJobApiV1GGuildIdImportsJobsJobIdDelete();

  const rows: Row[] = useMemo(() => {
    const merged: Row[] = [
      ...(exportsQuery.data ?? []).map((job) => ({ direction: "export" as const, job })),
      ...(importsQuery.data ?? []).map((job) => ({ direction: "import" as const, job })),
    ];
    return merged.sort(
      (a, b) => new Date(b.job.created_at).getTime() - new Date(a.job.created_at).getTime()
    );
  }, [exportsQuery.data, importsQuery.data]);

  if (exportsQuery.isLoading || importsQuery.isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }
  if (exportsQuery.isError || importsQuery.isError) {
    return <p className="py-4 text-destructive text-sm">{t("exports:table.loadFailed")}</p>;
  }
  if (rows.length === 0) {
    return <p className="py-4 text-muted-foreground text-sm">{t("exports:table.empty")}</p>;
  }

  const handleCancel = async (job: ImportJobRead) => {
    try {
      await cancelMutation.mutateAsync({ guildId, jobId: job.id });
    } catch (err) {
      // Most often a 409: the job started running between render and click.
      // Surface it instead of the row silently flipping to "running".
      toast.error(getErrorMessage(err, "imports:job.failed"));
    } finally {
      void queryClient.invalidateQueries({
        queryKey: getListImportJobsApiV1GGuildIdImportsJobsGetQueryKey(guildId),
      });
    }
  };

  const rowLabel = (row: Row): string => {
    if (row.direction === "export") {
      return t(`exports:table.source.${row.job.source}` as never, {
        defaultValue: row.job.source,
      });
    }
    return t(`imports:table.source.${row.job.source}` as never, {
      defaultValue: row.job.source,
    });
  };

  const rowStatus = (row: Row): string =>
    row.direction === "export" ? exportDisplayStatus(row.job) : row.job.status;

  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("exports:table.columns.export")}</TableHead>
            <TableHead>{t("exports:table.columns.status")}</TableHead>
            <TableHead className="hidden sm:table-cell">
              {t("exports:table.columns.created")}
            </TableHead>
            <TableHead className="text-right">
              <span className="sr-only">{t("exports:table.columns.actions")}</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => {
            const status = rowStatus(row);
            return (
              <TableRow key={`${row.direction}-${row.job.id}`}>
                <TableCell className="font-medium">
                  <Badge variant="outline" className="mr-2">
                    {t(`imports:table.direction.${row.direction}`)}
                  </Badge>
                  {rowLabel(row)}
                  {row.direction === "export" && (
                    <span className="ml-1 text-muted-foreground text-xs uppercase">
                      {row.job.format}
                    </span>
                  )}
                </TableCell>
                <TableCell>
                  <Badge variant={STATUS_VARIANT[status] ?? "secondary"}>
                    {row.direction === "export"
                      ? t(`exports:table.status.${status}` as never, { defaultValue: status })
                      : t(`imports:table.status.${status}` as never, { defaultValue: status })}
                  </Badge>
                </TableCell>
                <TableCell className="hidden text-muted-foreground text-sm sm:table-cell">
                  <RelativeTime date={row.job.created_at} />
                </TableCell>
                <TableCell className="text-right">
                  {row.direction === "export" && status === "done" && (
                    <Button
                      variant="outline"
                      size="sm"
                      aria-label={t("exports:table.download")}
                      onClick={() =>
                        void downloadExportArtifact(
                          guildId,
                          row.job.id,
                          t as (key: string, options?: Record<string, unknown>) => string,
                          row.job.source,
                          (row.job as ExportJobRead).format
                        )
                      }
                    >
                      <Download className="h-4 w-4" />
                      <span className="hidden sm:inline">{t("exports:table.download")}</span>
                    </Button>
                  )}
                  {row.direction === "import" && ACTIVE.has(row.job.status) && (
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={row.job.status === "running"}
                      aria-label={t("imports:table.cancel")}
                      onClick={() => void handleCancel(row.job as ImportJobRead)}
                    >
                      <X className="h-4 w-4" />
                      <span className="hidden sm:inline">{t("imports:table.cancel")}</span>
                    </Button>
                  )}
                  {row.direction === "import" &&
                    (row.job.status === "done" || row.job.status === "failed") && (
                      <Button
                        variant="outline"
                        size="sm"
                        aria-label={t("imports:table.viewReport")}
                        onClick={() => setReportJob(row.job as ImportJobRead)}
                      >
                        <FileText className="h-4 w-4" />
                        <span className="hidden sm:inline">{t("imports:table.viewReport")}</span>
                      </Button>
                    )}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
      <Dialog open={reportJob != null} onOpenChange={(open) => !open && setReportJob(null)}>
        <DialogContent className="max-h-[85vh] max-w-lg overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("imports:table.reportTitle")}</DialogTitle>
          </DialogHeader>
          {reportJob && <ImportReport job={reportJob} />}
        </DialogContent>
      </Dialog>
    </div>
  );
}
