import { formatDistanceToNow } from "date-fns";
import { Download, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useListExportJobsApiV1GGuildIdExportsGet } from "@/api/generated/exports/exports";
import type { ExportJobRead } from "@/api/generated/initiativeAPI.schemas";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useDateLocale } from "@/hooks/useDateLocale";
import { downloadExportArtifact } from "@/lib/exportDownload";

const ACTIVE = new Set(["queued", "running"]);
const POLL_MS = 5000;

const STATUS_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  done: "default",
  queued: "secondary",
  running: "secondary",
  failed: "destructive",
  expired: "outline",
};

function sourceKey(source: string): string {
  return `table.source.${source}`;
}

/** The guild's export jobs (RLS scopes rows: members see their own, guild
 * admins see everyone's), newest first, with re-download for finished,
 * unexpired artifacts. Polls while any job is still rendering so a wizard
 * export started moments ago flips to Ready without a reload. */
export function ExportJobsTable() {
  const { t } = useTranslation("exports");
  const guildId = useActiveGuildId();
  const dateLocale = useDateLocale();

  const jobsQuery = useListExportJobsApiV1GGuildIdExportsGet(guildId, {
    query: {
      refetchInterval: (query) =>
        (query.state.data ?? []).some((job) => ACTIVE.has(job.status)) ? POLL_MS : false,
    },
  });
  const jobs = jobsQuery.data ?? [];

  if (jobsQuery.isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }
  if (jobsQuery.isError) {
    return <p className="py-4 text-destructive text-sm">{t("table.loadFailed")}</p>;
  }
  if (jobs.length === 0) {
    return <p className="py-4 text-muted-foreground text-sm">{t("table.empty")}</p>;
  }

  const handleDownload = (job: ExportJobRead) =>
    downloadExportArtifact(
      guildId,
      job.id,
      t as (key: string, options?: Record<string, unknown>) => string,
      job.source,
      job.format
    );

  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("table.columns.export")}</TableHead>
            <TableHead>{t("table.columns.status")}</TableHead>
            <TableHead className="hidden sm:table-cell">{t("table.columns.created")}</TableHead>
            <TableHead className="hidden sm:table-cell">{t("table.columns.expires")}</TableHead>
            <TableHead className="text-right">
              <span className="sr-only">{t("table.columns.actions")}</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {jobs.map((job) => (
            <TableRow key={job.id}>
              <TableCell className="font-medium">
                {t(sourceKey(job.source) as never, { defaultValue: job.source })}
                <span className="ml-1 text-muted-foreground text-xs uppercase">{job.format}</span>
              </TableCell>
              <TableCell>
                <Badge variant={STATUS_VARIANT[job.status] ?? "secondary"}>
                  {t(`table.status.${job.status}` as never, { defaultValue: job.status })}
                </Badge>
              </TableCell>
              <TableCell className="hidden text-muted-foreground text-sm sm:table-cell">
                {formatDistanceToNow(new Date(job.created_at), {
                  addSuffix: true,
                  locale: dateLocale,
                })}
              </TableCell>
              <TableCell className="hidden text-muted-foreground text-sm sm:table-cell">
                {job.status === "done" && job.expires_at
                  ? formatDistanceToNow(new Date(job.expires_at), {
                      addSuffix: true,
                      locale: dateLocale,
                    })
                  : "—"}
              </TableCell>
              <TableCell className="text-right">
                {job.status === "done" && (
                  <Button
                    variant="outline"
                    size="sm"
                    aria-label={t("table.download")}
                    onClick={() => void handleDownload(job)}
                  >
                    <Download className="h-4 w-4" />
                    <span className="hidden sm:inline">{t("table.download")}</span>
                  </Button>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
