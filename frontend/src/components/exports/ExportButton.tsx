import { ChevronDown, FileDown, Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
import { useGetExportJobApiV1GGuildIdExportsJobIdGet } from "@/api/generated/exports/exports";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { toast } from "@/lib/chesterToast";
import { downloadBlob } from "@/lib/csv";
import { getErrorMessage } from "@/lib/errorMessage";
import { downloadExportArtifact, normalizeBlobError } from "@/lib/exportDownload";
import { getItem, removeItem, setItem } from "@/lib/storage";

export interface ExportFormatOption {
  /** The ``format`` query value ("pdf", "csv", "xlsx", "md", "json"). */
  format: string;
  /** tasks-namespace key for the menu entry. */
  labelKey: string;
  /** Extra query params for this entry (e.g. ``{ layout: "checklist" }``). */
  extraParams?: Record<string, string>;
  /** Per-option filename stem override (e.g. the json backup's
   * ``{name}-{date}.initiative-project`` convention). */
  filenameStem?: string;
}

export interface ExportButtonProps {
  /** Source create route, e.g. "/exports/tasks" — relative to /g/{guildId}. */
  endpoint: string;
  /** The selector for the snapshot (filters, ids, project id, …). */
  params: Record<string, unknown>;
  /** Format menu entries; a single entry renders a plain button (no menu). */
  formats: ExportFormatOption[];
  /** Filename stem for inline downloads: ``{stem}.{format}``. */
  filenameStem: string;
  /** Idle-state label override; the busy label stays the shared "Exporting…". */
  label?: string;
  /** Adopt a stored pending job on mount. Exactly ONE instance per view may
   * set this — the guild's pending key is shared across every export surface,
   * so a second adopter would handle the same job again (duplicate download
   * + toast). Every instance still WRITES the key on 202, so a job started
   * anywhere is resumed by the adopting instance on the next mount. */
  resumePending?: boolean;
  variant?: "outline" | "default";
  /** Client-side entries appended to the menu (e.g. whiteboard PNG/SVG,
   * which only Excalidraw's own renderer can produce — the server never
   * renders scenes). Forces the menu even with a single engine format. */
  extraActions?: { labelKey: string; onSelect: () => void }[];
}

const POLL_MS = 2000;
const TERMINAL = new Set(["done", "failed", "expired"]);

// A pending job id survives the component unmounting (navigation) so a
// return to an adopting view resumes the poll and delivers the download.
// A full page reload is covered by the worker's inbox notification instead.
const pendingKey = (guildId: number) => `exports:pending:${guildId}`;

export function ExportButton({
  endpoint,
  params,
  formats,
  filenameStem,
  label,
  resumePending,
  variant = "outline",
  extraActions = [],
}: ExportButtonProps) {
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
      job.source,
      job.format
    );
  }, [job, jobId, guildId, t]);

  const busy = requesting || jobId != null;

  const handleExport = async (option: ExportFormatOption) => {
    if (busy || !guildId) {
      return;
    }
    setRequesting(true);
    try {
      // The generated client discards the HTTP status (mutator returns data
      // only), and these endpoints are a 200-file / 202-job union — call the
      // shared axios instance directly so auth interceptors and the
      // conditions/sorting paramsSerializer still apply.
      const res = await apiClient.get<Blob>(`/g/${guildId}${endpoint}`, {
        params: { ...params, format: option.format, ...option.extraParams },
        responseType: "blob",
        validateStatus: (s) => s === 200 || s === 202,
      });
      if (res.status === 200) {
        downloadBlob(res.data, `${option.filenameStem ?? filenameStem}.${option.format}`);
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
  // A single engine format with no extras needs no menu — the button IS the
  // action. In menu mode the trigger must NOT carry an onClick, or opening
  // the menu would also fire an export.
  const menuMode = formats.length > 1 || extraActions.length > 0;
  const trigger = (withChevron: boolean) => (
    <Button
      variant={variant}
      size="sm"
      disabled={busy}
      aria-label={idleLabel}
      title={idleLabel}
      onClick={menuMode ? undefined : () => void handleExport(formats[0])}
    >
      {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileDown className="h-4 w-4" />}
      <span className="hidden sm:ml-2 sm:inline">{busy ? t("export.preparing") : idleLabel}</span>
      {withChevron && !busy && <ChevronDown className="ml-1 h-3 w-3 opacity-60" />}
    </Button>
  );

  if (!menuMode) {
    return trigger(false);
  }
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>{trigger(true)}</DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {formats.map((option) => (
          <DropdownMenuItem key={option.labelKey} onSelect={() => void handleExport(option)}>
            {t(option.labelKey as never)}
          </DropdownMenuItem>
        ))}
        {extraActions.map((action) => (
          <DropdownMenuItem key={action.labelKey} onSelect={action.onSelect}>
            {t(action.labelKey as never)}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
