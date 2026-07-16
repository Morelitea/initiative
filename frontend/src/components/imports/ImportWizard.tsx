import { AlertTriangle, CheckCircle2, ChevronLeft, FileUp, Loader2, XCircle } from "lucide-react";
import { type ChangeEvent, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  useCancelImportJobApiV1GGuildIdImportsJobsJobIdDelete,
  useConfirmBackupImportApiV1GGuildIdImportsJobsJobIdConfirmPost,
  useUploadBackupApiV1GGuildIdImportsBackupPost,
} from "@/api/generated/imports/imports";
import type { ImportJobRead } from "@/api/generated/initiativeAPI.schemas";
import { ImportReport } from "@/components/imports/ImportReport";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useImportJob } from "@/hooks/useImportJob";
import { BackupPeekError, type PeekedManifest, peekBackupManifest } from "@/lib/backupPeek";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { formatBytes } from "@/lib/fileUtils";

// Mirrors the backend's IMPORT_MAX_BACKUP_UPLOAD_BYTES default — the UX
// layer; the server (ASGI middleware + bounded read) is the enforcement.
const MAX_UPLOAD_BYTES = 268_435_456;

export interface ImportWizardProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type Step = "pick" | "peek" | "uploading" | "plan" | "progress" | "report";

/** The backup import flow: pick a zip → local manifest preview (nothing
 * uploaded yet — the zip's central directory is read in-browser) → upload →
 * the server's authoritative plan → confirm → poll to the report. Closing
 * the dialog after confirm doesn't cancel the job; the report also lands in
 * the Data tab's jobs table and the inbox notification. */
export function ImportWizard({ open, onOpenChange }: ImportWizardProps) {
  const { t } = useTranslation("imports");
  const guildId = useActiveGuildId();
  const importJob = useImportJob();

  const [step, setStep] = useState<Step>("pick");
  const [file, setFile] = useState<File | null>(null);
  const [peeked, setPeeked] = useState<PeekedManifest | null>(null);
  const [pickError, setPickError] = useState<string | null>(null);
  const [stagedJob, setStagedJob] = useState<ImportJobRead | null>(null);

  const uploadMutation = useUploadBackupApiV1GGuildIdImportsBackupPost();
  const confirmMutation = useConfirmBackupImportApiV1GGuildIdImportsJobsJobIdConfirmPost();
  const cancelMutation = useCancelImportJobApiV1GGuildIdImportsJobsJobIdDelete();

  // biome-ignore lint/correctness/useExhaustiveDependencies: runs only on open/close; job state is read at that moment
  useEffect(() => {
    if (!open) {
      setStep("pick");
      setFile(null);
      setPeeked(null);
      setPickError(null);
      setStagedJob(null);
      importJob.reset();
    } else if (importJob.busy) {
      // A job from a previous wizard session is still applying — resume its
      // progress view instead of offering a new flow.
      setStep("progress");
    }
  }, [open]);

  // The poll ending flips progress → report.
  useEffect(() => {
    if (step === "progress" && importJob.terminal != null) {
      setStep("report");
    }
  }, [step, importJob.terminal]);

  const handleFileChange = async (e: ChangeEvent<HTMLInputElement>) => {
    setPickError(null);
    setPeeked(null);
    const picked = e.target.files?.[0];
    if (!picked) {
      return;
    }
    if (picked.size > MAX_UPLOAD_BYTES) {
      setPickError(t("wizard.pick.tooLarge", { limit: formatBytes(MAX_UPLOAD_BYTES) }));
      return;
    }
    try {
      const manifest = await peekBackupManifest(picked);
      setFile(picked);
      setPeeked(manifest);
      setStep("peek");
    } catch (err) {
      setPickError(
        err instanceof BackupPeekError ? t("wizard.pick.notZip") : t("wizard.pick.notZip")
      );
    }
  };

  const handleUpload = async () => {
    if (!file) {
      return;
    }
    setStep("uploading");
    try {
      const job = await uploadMutation.mutateAsync({ guildId, data: { file } });
      setStagedJob(job);
      setStep("plan");
    } catch (err) {
      toast.error(getErrorMessage(err, "imports:envelope.error"));
      setStep("peek");
    }
  };

  const handleConfirm = async () => {
    if (!stagedJob) {
      return;
    }
    try {
      const job = await confirmMutation.mutateAsync({
        guildId,
        jobId: stagedJob.id,
        data: {},
      });
      importJob.watch(job.id);
      setStep("progress");
    } catch (err) {
      toast.error(getErrorMessage(err, "imports:envelope.error"));
    }
  };

  const handleCancelStaged = async () => {
    if (!stagedJob) {
      onOpenChange(false);
      return;
    }
    try {
      await cancelMutation.mutateAsync({ guildId, jobId: stagedJob.id });
    } catch {
      // Already expired/started — nothing to cancel; closing is still right.
    }
    onOpenChange(false);
  };

  const plan = stagedJob?.plan as
    | {
        source_guild_name?: string;
        app_version?: string;
        exported_at?: string;
        initiatives?: Array<{
          source_id: number;
          name: string;
          proposed_name: string;
          entry_counts: Record<string, number>;
        }>;
        asset_count?: number;
        asset_bytes?: number;
        skipped?: unknown[];
        unknown_types?: string[];
      }
    | null
    | undefined;

  const peekSummary = useMemo(() => {
    if (!peeked) {
      return null;
    }
    return {
      guildName: peeked.guild?.name ?? "",
      appVersion: peeked.app_version ?? "",
      exportedAt: peeked.exported_at ? new Date(peeked.exported_at).toLocaleString() : "",
      initiativeCount: peeked.initiatives?.length ?? 0,
      entryCount: peeked.entries?.length ?? 0,
      assetCount: peeked.assets?.length ?? 0,
      assetBytes: (peeked.assets ?? []).reduce((sum, a) => sum + (a.size_bytes ?? 0), 0),
    };
  }, [peeked]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-lg overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("wizard.title")}</DialogTitle>
          {step === "pick" && <DialogDescription>{t("wizard.pick.hint")}</DialogDescription>}
          {step === "plan" && <DialogDescription>{t("wizard.plan.prompt")}</DialogDescription>}
        </DialogHeader>

        {step === "peek" && (
          <Button variant="ghost" size="sm" className="w-fit" onClick={() => setStep("pick")}>
            <ChevronLeft className="mr-1 h-4 w-4" />
            {t("wizard.back")}
          </Button>
        )}

        {step === "pick" && (
          <div className="space-y-3">
            <label className="flex cursor-pointer flex-col items-center gap-2 rounded-lg border border-dashed p-8 text-center transition-colors hover:bg-accent">
              <FileUp className="h-8 w-8 text-muted-foreground" />
              <span className="font-medium text-sm">{t("wizard.pick.prompt")}</span>
              <input
                type="file"
                accept=".zip,application/zip"
                className="hidden"
                onChange={handleFileChange}
              />
            </label>
            {pickError && <p className="text-destructive text-sm">{pickError}</p>}
          </div>
        )}

        {step === "peek" && peekSummary && (
          <div className="space-y-4">
            <div className="space-y-1 rounded-lg border p-3 text-sm">
              <p className="font-medium">
                {t("wizard.peek.source", { name: peekSummary.guildName })}
              </p>
              <p className="text-muted-foreground text-xs">
                {t("wizard.peek.exportedAt", {
                  date: peekSummary.exportedAt,
                  version: peekSummary.appVersion,
                })}
              </p>
              <p className="text-muted-foreground text-xs">
                {t("wizard.peek.initiative", { count: peekSummary.initiativeCount })} ·{" "}
                {t("wizard.peek.entries", { count: peekSummary.entryCount })}
              </p>
              <p className="text-muted-foreground text-xs">
                {peekSummary.assetCount > 0
                  ? t("wizard.peek.assets", {
                      count: peekSummary.assetCount,
                      size: formatBytes(peekSummary.assetBytes),
                    })
                  : t("wizard.peek.noAssets")}
              </p>
            </div>
            <p className="text-muted-foreground text-xs">{t("wizard.peek.note")}</p>
            <Button className="w-full" onClick={() => void handleUpload()}>
              {t("wizard.upload")}
            </Button>
          </div>
        )}

        {step === "uploading" && (
          <div className="flex flex-col items-center gap-3 py-8">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            <p className="text-muted-foreground text-sm">{t("wizard.uploading")}</p>
          </div>
        )}

        {step === "plan" && plan && (
          <div className="space-y-4">
            <div className="space-y-2">
              {(plan.initiatives ?? []).map((initiative) => (
                <div key={initiative.source_id} className="space-y-1 rounded-lg border p-3">
                  <p className="font-medium text-sm">
                    {t("wizard.plan.willCreate", {
                      name: initiative.name,
                      proposed: initiative.proposed_name,
                    })}
                  </p>
                  <p className="text-muted-foreground text-xs">
                    {Object.entries(initiative.entry_counts)
                      .map(([tool, count]) => `${tool}: ${count}`)
                      .join(" · ")}
                  </p>
                </div>
              ))}
            </div>
            {(plan.skipped?.length ?? 0) > 0 && (
              <p className="flex items-start gap-2 text-muted-foreground text-xs">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                {t("wizard.plan.skipped", { count: plan.skipped?.length ?? 0 })}
              </p>
            )}
            {(plan.unknown_types?.length ?? 0) > 0 && (
              <p className="flex items-start gap-2 text-muted-foreground text-xs">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                {t("wizard.plan.unknownTypes", {
                  types: (plan.unknown_types ?? []).join(", "),
                })}
              </p>
            )}
            <p className="text-muted-foreground text-xs">{t("wizard.plan.note")}</p>
            <div className="flex gap-2">
              <Button
                variant="outline"
                className="flex-1"
                onClick={() => void handleCancelStaged()}
              >
                {t("wizard.cancelUpload")}
              </Button>
              <Button
                className="flex-1"
                disabled={confirmMutation.isPending}
                onClick={() => void handleConfirm()}
              >
                {t("wizard.start")}
              </Button>
            </div>
          </div>
        )}

        {step === "progress" && (
          <div className="flex flex-col items-center gap-3 py-6 text-center">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            <p className="font-medium text-sm">{t("wizard.progress.title")}</p>
            <p className="text-muted-foreground text-xs">{t("wizard.progress.note")}</p>
            <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
              {t("wizard.close")}
            </Button>
          </div>
        )}

        {step === "report" && importJob.terminal && (
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              {importJob.terminal.status === "done" ? (
                <>
                  <CheckCircle2 className="h-6 w-6 text-primary" />
                  <p className="font-medium">{t("wizard.report.title")}</p>
                </>
              ) : (
                <>
                  <XCircle className="h-6 w-6 text-destructive" />
                  <p className="font-medium">{t("wizard.report.failedTitle")}</p>
                </>
              )}
            </div>
            <ImportReport job={importJob.terminal} />
            <Button className="w-full" onClick={() => onOpenChange(false)}>
              {t("wizard.close")}
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
