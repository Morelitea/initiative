import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
import { useGetExportJobApiV1GGuildIdExportsJobIdGet } from "@/api/generated/exports/exports";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { toast } from "@/lib/chesterToast";
import { downloadBlob } from "@/lib/csv";
import { getErrorMessage } from "@/lib/errorMessage";
import {
  downloadExportArtifact,
  filenameFromDisposition,
  normalizeBlobError,
} from "@/lib/exportDownload";
import { getItem, removeItem, setItem } from "@/lib/storage";

const POLL_MS = 2000;
const TERMINAL = new Set(["done", "failed", "expired"]);

// A pending job id survives the component unmounting (navigation) so a
// return to an adopting view resumes the poll and delivers the download.
// A full page reload is covered by the worker's inbox notification instead.
const pendingKey = (guildId: number) => `exports:pending:${guildId}`;

export type ExportJobPhase = "idle" | "requesting" | "polling" | "done" | "failed";

export interface StartExportOptions {
  /** Source create route, e.g. "/exports/tasks" — relative to /g/{guildId}. */
  endpoint: string;
  /** Query params: the selector plus format. A browser tz is added unless
   * the caller passes an explicit one. */
  params: Record<string, unknown>;
  /** Inline-download filename when the server sends no Content-Disposition. */
  fallbackFilename?: string;
}

export interface UseExportJobOptions {
  /** Adopt a stored pending job on mount. Exactly ONE instance per view may
   * set this — the guild's pending key is shared across every export surface,
   * so a second adopter would handle the same job again (duplicate download
   * + toast). Every instance still WRITES the key on 202, so a job started
   * anywhere is resumed by the adopting instance on the next mount. */
  resumePending?: boolean;
}

/** The engine's request → 200-inline-download | 202-poll-then-download flow,
 * shared by ExportButton and the export wizard. Toasts (queued / success /
 * failed) live here so every surface reports identically. */
export function useExportJob({ resumePending = false }: UseExportJobOptions = {}) {
  const { t } = useTranslation("exports");
  const guildId = useActiveGuildId();
  const [requesting, setRequesting] = useState(false);
  // The last terminal outcome, until the next start()/reset() — what lets a
  // wizard show a done/failed screen after the poll ends.
  const [outcome, setOutcome] = useState<"done" | "failed" | null>(null);
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
      setOutcome("failed");
      toast.error(t("export.failed"));
      return;
    }
    setOutcome("done");
    void downloadExportArtifact(
      guildId,
      jobId,
      t as (key: string, options?: Record<string, unknown>) => string,
      job.source,
      job.format
    );
  }, [job, jobId, guildId, t]);

  const start = async (options: StartExportOptions): Promise<void> => {
    if (requesting || jobId != null || !guildId) {
      return;
    }
    setRequesting(true);
    setOutcome(null);
    try {
      // The generated client discards the HTTP status (mutator returns data
      // only), and these endpoints are a 200-file / 202-job union — call the
      // shared axios instance directly so auth interceptors and the
      // conditions/sorting paramsSerializer still apply.
      const res = await apiClient.get<Blob>(`/g/${guildId}${options.endpoint}`, {
        // tz: report timestamps ("generated at …") render in the browser's
        // zone, not UTC. First so an explicit caller tz in params wins.
        params: {
          tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
          ...options.params,
        },
        responseType: "blob",
        validateStatus: (s) => s === 200 || s === 202,
      });
      if (res.status === 200) {
        // Prefer the server-chosen name (Content-Disposition): a file
        // passthrough keeps an extension the client can't know, and bundles
        // arrive as .zip regardless of the chosen format.
        const serverName = filenameFromDisposition(res.headers["content-disposition"]);
        downloadBlob(res.data, serverName ?? options.fallbackFilename ?? `export-${Date.now()}`);
        setOutcome("done");
        toast.success(t("export.success"));
      } else {
        const queued = JSON.parse(await res.data.text()) as { id: number };
        setJobId(queued.id);
        setItem(pendingKey(guildId), String(queued.id));
        toast.success(t("export.queued"));
      }
    } catch (err) {
      setOutcome("failed");
      toast.error(getErrorMessage(await normalizeBlobError(err), "tasks:export.error"));
    } finally {
      setRequesting(false);
    }
  };

  const reset = () => {
    setOutcome(null);
  };

  const phase: ExportJobPhase = requesting
    ? "requesting"
    : jobId != null
      ? "polling"
      : (outcome ?? "idle");

  return {
    /** True while a request is in flight or a job is being polled. */
    busy: requesting || jobId != null,
    phase,
    jobId,
    start,
    reset,
  };
}
