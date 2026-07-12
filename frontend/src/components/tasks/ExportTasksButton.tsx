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

type ExportParams = Pick<
  ExportTasksApiV1GGuildIdExportsTasksGetParams,
  "conditions" | "sorting" | "tz" | "include_archived"
>;

interface ExportTasksButtonProps {
  /** The CURRENT list selector — the export must match what's on screen. */
  params: ExportParams;
}

const POLL_MS = 2000;
const TERMINAL = new Set(["done", "failed", "expired"]);

/** Axios error bodies arrive as Blobs under responseType "blob"; recover the
 * JSON detail so getErrorMessage can map it to a localized message. */
async function normalizeBlobError(err: unknown): Promise<unknown> {
  const response = (err as { response?: { data?: unknown } })?.response;
  if (response?.data instanceof Blob) {
    try {
      response.data = JSON.parse(await response.data.text());
    } catch {
      // keep the original error
    }
  }
  return err;
}

export function ExportTasksButton({ params }: ExportTasksButtonProps) {
  const { t } = useTranslation("tasks");
  const guildId = useActiveGuildId();
  const [requesting, setRequesting] = useState(false);
  const [jobId, setJobId] = useState<number | null>(null);
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
    if (job.status !== "done") {
      toast.error(t("export.failed"));
      return;
    }
    apiClient
      .get<Blob>(`/g/${guildId}/exports/${jobId}/download`, { responseType: "blob" })
      .then((res) => {
        downloadBlob(res.data, `tasks-${jobId}.pdf`);
        toast.success(t("export.success"));
      })
      .catch(async (err) => {
        toast.error(getErrorMessage(await normalizeBlobError(err), "tasks:export.error"));
      });
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
        toast.success(t("export.queued"));
      }
    } catch (err) {
      toast.error(getErrorMessage(await normalizeBlobError(err), "tasks:export.error"));
    } finally {
      setRequesting(false);
    }
  };

  return (
    <Button
      variant="outline"
      size="sm"
      onClick={handleExport}
      disabled={busy}
      aria-label={t("export.button")}
      title={t("export.button")}
    >
      {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileDown className="h-4 w-4" />}
      <span className="hidden sm:ml-2 sm:inline">
        {busy ? t("export.preparing") : t("export.button")}
      </span>
    </Button>
  );
}
