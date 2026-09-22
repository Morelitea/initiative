import { AlertTriangle, CheckCircle2, FileUp, Loader2, XCircle } from "lucide-react";
import { type ChangeEvent, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  useCancelImportJobApiV1GGuildIdImportsJobsJobIdDelete,
  useConfirmImportApiV1GGuildIdImportsJobsJobIdConfirmPost,
  useUploadBackupApiV1GGuildIdImportsBackupPost,
} from "@/api/generated/imports/imports";
import type { ImportJobRead } from "@/api/generated/initiativeAPI.schemas";
import { ImportPeopleStep, type PlanPerson } from "@/components/imports/ImportPeopleStep";
import { ImportReport } from "@/components/imports/ImportReport";
import { Button } from "@/components/ui/button";
import { WizardDialog } from "@/components/ui/wizard-dialog";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useImportJob } from "@/hooks/useImportJob";
import { useWizard } from "@/hooks/useWizard";
import { BackupPeekError, type PeekedManifest, peekBackupManifest } from "@/lib/backupPeek";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { formatBytes } from "@/lib/fileUtils";
import { formatDateTime } from "@/lib/formatDate";

// Mirrors the backend's IMPORT_MAX_BACKUP_UPLOAD_BYTES default — the UX
// layer; the server (ASGI middleware + bounded read) is the enforcement.
const MAX_UPLOAD_BYTES = 268_435_456;

export interface ImportWizardProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type Step = "pick" | "peek" | "uploading" | "plan" | "people" | "progress" | "report";

/** The backup import flow: pick a zip → local manifest preview (nothing
 * uploaded yet — the zip's central directory is read in-browser) → upload →
 * the server's authoritative plan → say who the archive's people are, where
 * it quotes anybody → confirm → poll to the report. Closing
 * the dialog after confirm doesn't cancel the job; the report also lands in
 * the Data tab's jobs table and the inbox notification. */
export function ImportWizard({ open, onOpenChange }: ImportWizardProps) {
  const { t } = useTranslation("imports");
  const guildId = useActiveGuildId();
  const importJob = useImportJob();

  const { step, go, commit, back, reset } = useWizard<Step>("pick");
  const [file, setFile] = useState<File | null>(null);
  const [peeked, setPeeked] = useState<PeekedManifest | null>(null);
  const [pickError, setPickError] = useState<string | null>(null);
  const [stagedJob, setStagedJob] = useState<ImportJobRead | null>(null);
  // Source handle → the account picked for it. Seeded from the plan's exact
  // matches; a handle left out of it stays unmapped on purpose.
  const [peopleMap, setPeopleMap] = useState<Record<string, number | null>>({});

  const uploadMutation = useUploadBackupApiV1GGuildIdImportsBackupPost();
  const confirmMutation = useConfirmImportApiV1GGuildIdImportsJobsJobIdConfirmPost();
  const cancelMutation = useCancelImportJobApiV1GGuildIdImportsJobsJobIdDelete();

  // biome-ignore lint/correctness/useExhaustiveDependencies: runs only on open/close; job state is read at that moment
  useEffect(() => {
    if (!open) {
      reset();
      setFile(null);
      setPeeked(null);
      setPickError(null);
      setStagedJob(null);
      setPeopleMap({});
      importJob.reset();
    } else if (importJob.busy) {
      // A job from a previous wizard session is still applying — resume its
      // progress view instead of offering a new flow.
      commit("progress");
    }
  }, [open]);

  // Seed the mapping from the plan's exact matches, once, when the plan
  // arrives. Only the suggestions: a person the server could not match is
  // left blank for somebody to answer.
  useEffect(() => {
    const suggested = (stagedJob?.plan as { people?: PlanPerson[] } | null)?.people;
    if (!suggested) {
      return;
    }
    setPeopleMap(
      Object.fromEntries(
        suggested
          .filter((person) => person.suggested_user_id != null)
          .map((person) => [person.handle, person.suggested_user_id as number])
      )
    );
  }, [stagedJob]);

  // The poll ending flips progress → report.
  useEffect(() => {
    if (step === "progress" && importJob.terminal != null) {
      commit("report");
    }
  }, [step, importJob.terminal, commit]);

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
      go("peek");
    } catch (err) {
      // "not_backup" → wrong/corrupt file; "unreadable" (and any non-peek
      // throw: a DecompressionStream/TextDecoder failure, OOM) → we couldn't
      // read the zip.
      setPickError(
        err instanceof BackupPeekError && err.code === "not_backup"
          ? t("wizard.pick.notZip")
          : t("wizard.pick.readFailed")
      );
    }
  };

  const handleUpload = async () => {
    if (!file) {
      return;
    }
    go("uploading");
    try {
      const job = await uploadMutation.mutateAsync({ guildId, data: { file } });
      setStagedJob(job);
      commit("plan");
    } catch (err) {
      toast.error(getErrorMessage(err, "imports:envelope.error"));
      back();
    }
  };

  const handleConfirm = async () => {
    if (!stagedJob) {
      return;
    }
    // Only the rows somebody actually pointed at an account travel. A blank
    // row is an answer — "nobody here" — and saying nothing is how it is said.
    const mapped = Object.fromEntries(Object.entries(peopleMap).filter(([, id]) => id != null));
    try {
      const job = await confirmMutation.mutateAsync({
        guildId,
        jobId: stagedJob.id,
        data: Object.keys(mapped).length > 0 ? { people_map: mapped } : {},
      });
      importJob.watch(job.id);
      commit("progress");
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
        people?: PlanPerson[];
      }
    | null
    | undefined;

  const people = plan?.people ?? [];

  const peekSummary = useMemo(() => {
    if (!peeked) {
      return null;
    }
    return {
      guildName: peeked.guild?.name ?? "",
      appVersion: peeked.app_version ?? "",
      exportedAt: formatDateTime(peeked.exported_at),
      initiativeCount: peeked.initiatives?.length ?? 0,
      entryCount: peeked.entries?.length ?? 0,
      assetCount: peeked.assets?.length ?? 0,
      assetBytes: (peeked.assets ?? []).reduce((sum, a) => sum + (a.size_bytes ?? 0), 0),
    };
  }, [peeked]);

  const stepDescription =
    step === "pick"
      ? t("wizard.pick.hint")
      : step === "plan"
        ? t("wizard.plan.prompt")
        : step === "people"
          ? t("wizard.people.prompt")
          : null;

  // The questions to answer; the upload, the run and the report are what
  // happens afterwards. The fourth appears only where the archive quotes
  // somebody — a backup with no comments in it has nobody to ask about.
  const total = people.length > 0 ? 4 : 3;
  const position: Record<Step, number | null> = {
    pick: 1,
    peek: 2,
    uploading: null,
    plan: 3,
    people: 4,
    progress: null,
    report: null,
  };
  const current = position[step];

  return (
    <WizardDialog
      open={open}
      onOpenChange={onOpenChange}
      className="max-h-[85vh] overflow-y-auto sm:max-w-lg"
      title={t("wizard.title")}
      description={stepDescription}
      progress={current === null ? undefined : { current, total }}
      // Here, and back out of the people step — the two places where going
      // back costs nothing. Between them the file is uploaded and a job is
      // staged, and the way out of that is Cancel, which deletes it.
      onBack={step === "peek" || step === "people" ? back : undefined}
      backLabel={t("wizard.back")}
    >
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
            <Button variant="outline" className="flex-1" onClick={() => void handleCancelStaged()}>
              {t("wizard.cancelUpload")}
            </Button>
            {people.length > 0 ? (
              <Button className="flex-1" onClick={() => go("people")}>
                {t("wizard.next")}
              </Button>
            ) : (
              <Button
                className="flex-1"
                disabled={confirmMutation.isPending}
                onClick={() => void handleConfirm()}
              >
                {t("wizard.start")}
              </Button>
            )}
          </div>
        </div>
      )}

      {step === "people" && (
        <div className="space-y-4">
          <ImportPeopleStep people={people} value={peopleMap} onChange={setPeopleMap} />
          <div className="flex gap-2">
            <Button variant="outline" className="flex-1" onClick={() => void handleCancelStaged()}>
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
    </WizardDialog>
  );
}
