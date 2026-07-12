import { FileDown, Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
import { useGetExportJobApiV1GGuildIdExportsJobIdGet } from "@/api/generated/exports/exports";
import type { ExportTasksApiV1GGuildIdExportsTasksGetParams } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { toast } from "@/lib/chesterToast";
import { downloadBlob } from "@/lib/csv";
import { getErrorMessage } from "@/lib/errorMessage";
import { downloadExportArtifact, normalizeBlobError } from "@/lib/exportDownload";
import { getItem, removeItem, setItem } from "@/lib/storage";

export type ExportParams = Pick<
  ExportTasksApiV1GGuildIdExportsTasksGetParams,
  "conditions" | "sorting" | "tz" | "include_archived"
>;

interface ExportTasksButtonProps {
  /** The selector for the snapshot — the current list filters, or an
   * ``id in_`` condition for an explicit selection. */
  params: ExportParams;
  /** Idle-state label override (e.g. "Export Selected"); the busy label
   * stays the shared "Exporting…". */
  label?: string;
  /** Adopt a stored pending job on mount. Exactly ONE instance per view may
   * set this (the persistent toolbar button) — the guild's pending key is
   * shared, so a second adopter (e.g. the bulk-selection button mounting
   * mid-poll) would handle the same job again: duplicate download + toast.
   * Every instance still WRITES the key on 202, so a job started anywhere
   * is resumed by the adopting instance on the next mount. */
  resumePending?: boolean;
}

const POLL_MS = 2000;
const TERMINAL = new Set(["done", "failed", "expired"]);

// A pending job id survives the component unmounting (navigation) so a
// return to any tasks view resumes the poll and still delivers the download.
// A full page reload is covered by the worker's inbox notification instead.
const pendingKey = (guildId: number) => `exports:pending:${guildId}`;

export function ExportTasksButton({ params, label, resumePending }: ExportTasksButtonProps) {
  const { t } = useTranslation("tasks");
  const guildId = useActiveGuildId();
  const [requesting, setRequesting] = useState(false);
  const [jobId, setJobId] = useState<number | null>(() => {
    if (!resumePending || !guildId) {
      return null;
    }
    const stored = Number(getItem(pendingKey(guildId)));
    return Number.isFinite(stored) && stored > 0 ? stored : null;
  });
  // Job ids already handled — a terminal status must fire exactly once even
  // though polling re-renders keep delivering it.
  const handledJobs = useRef(new Set<number>());

  const jobQuery = useGetExportJobApiV1GGuildIdExportsJobIdGet(guildId, jobId ?? 0, {
    query: {
      enabled: jobId != null,
      refetchInterval: (query) => (TERMINAL.has(query.state.data?.status ?? "") ? false : POLL_MS),
    },
  });

  const job = jobQuery.data;
  useEffect(() => {
    if (!jobId || !job || job.id !== jobId || !TERMINAL.has(job.status)) {
      return;
    }
    if (handledJobs.current.has(jobId)) {
      return;
    }
    handledJobs.current.add(jobId);
    setJobId(null);
    removeItem(pendingKey(guildId));
    if (job.status !== "done") {
      toast.error(t("export.failed"));
      return;
    }
    void downloadExportArtifact(
      guildId,
      jobId,
      t as (key: string, options?: Record<string, unknown>) => string,
      job.source
    );
  }, [job, jobId, guildId, t]);

  const busy = requesting || jobId != null;

  const handleExport = async () => {
    if (busy || !guildId) {
      return;
    }
    setRequesting(true);
    try {
      // The generated client discards the HTTP status (mutator returns data
      // only), and this endpoint is a 200-PDF / 202-job union — call the
      // shared axios instance directly so auth/guild interceptors and the
      // conditions/sorting paramsSerializer still apply.
      const res = await apiClient.get<Blob>(`/g/${guildId}/exports/tasks`, {
        params: { ...params, format: "pdf" },
        responseType: "blob",
        validateStatus: (s) => s === 200 || s === 202,
      });
      if (res.status === 200) {
        downloadBlob(res.data, "tasks.pdf");
        toast.success(t("export.success"));
      } else {
        const queued = JSON.parse(await res.data.text()) as { id: number };
        setJobId(queued.id);
        setItem(pendingKey(guildId), String(queued.id));
        toast.success(t("export.queued"));
      }
    } catch (err) {
      toast.error(getErrorMessage(await normalizeBlobError(err), "tasks:export.error"));
    } finally {
      setRequesting(false);
    }
  };

  const idleLabel = label ?? t("export.button");
  return (
    <Button
      variant="outline"
      size="sm"
      onClick={handleExport}
      disabled={busy}
      aria-label={idleLabel}
      title={idleLabel}
    >
      {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileDown className="h-4 w-4" />}
      <span className="hidden sm:ml-2 sm:inline">{busy ? t("export.preparing") : idleLabel}</span>
    </Button>
  );
}
