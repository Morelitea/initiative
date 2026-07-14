import { AlertTriangle, CheckCircle2, ChevronLeft, Loader2, XCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { useEstimateAggregateExportApiV1GGuildIdExportsEstimateGet } from "@/api/generated/exports/exports";
import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  AGGREGATE_EXPORT_TOOLS,
  REPORT_DOCUMENT_FORMATS,
  REPORT_TOOL_FORMATS,
} from "@/components/exports/formats";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Switch } from "@/components/ui/switch";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useExportJob } from "@/hooks/useExportJob";
import { formatBytes } from "@/lib/fileUtils";
import { toolNavLabelKey } from "@/lib/tools";

export interface ExportWizardProps {
  scope: "initiative" | "guild";
  /** Required when scope is "initiative". */
  initiativeId?: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type Step = "mode" | "backup" | "report" | "confirm" | "progress";
type Mode = "backup" | "report";

const DEFAULT_DOCUMENT_FORMATS = { native: "pdf", spreadsheet: "xlsx" };

/** The aggregate export flow: mode → (backup options with live estimate |
 * per-tool report formats) → confirm → progress. Delivery is the shared
 * useExportJob poll — closing the dialog mid-render doesn't cancel the job,
 * the download still arrives (and lands in the settings exports table). */
export function ExportWizard({ scope, initiativeId, open, onOpenChange }: ExportWizardProps) {
  const { t } = useTranslation("exports");
  const guildId = useActiveGuildId();
  const exportJob = useExportJob();

  const [step, setStep] = useState<Step>("mode");
  const [mode, setMode] = useState<Mode>("backup");
  const [include, setInclude] = useState<Record<string, boolean>>({});
  const [includeUploads, setIncludeUploads] = useState(true);
  const [formats, setFormats] = useState<Record<string, string>>({});
  const [documentFormats, setDocumentFormats] = useState(DEFAULT_DOCUMENT_FORMATS);

  // Reset to a fresh flow when the dialog closes (state only — a job already
  // started keeps polling in the hook and delivers regardless).
  // biome-ignore lint/correctness/useExhaustiveDependencies: reset runs only on close; exportJob.reset is stable-enough and adding it would re-fire on every poll tick
  useEffect(() => {
    if (!open) {
      setStep("mode");
      setMode("backup");
      setInclude({});
      setIncludeUploads(true);
      setFormats({});
      setDocumentFormats(DEFAULT_DOCUMENT_FORMATS);
      exportJob.reset();
    }
  }, [open]);

  const estimateQuery = useEstimateAggregateExportApiV1GGuildIdExportsEstimateGet(
    guildId,
    { scope, initiative_id: initiativeId ?? null, include_uploads: includeUploads },
    { query: { enabled: open && step === "backup" } }
  );
  const estimate = estimateQuery.data;

  const included = (tool: Tool) => include[tool] !== false;
  const setIncluded = (tool: Tool, value: boolean) =>
    setInclude((prev) => ({ ...prev, [tool]: value }));

  const toolDisabled = (tool: Tool) => estimate?.tools?.[tool]?.disabled === true;
  const visibleTools = AGGREGATE_EXPORT_TOOLS;

  const overRowLimit =
    estimate != null && (estimate.estimated_rows ?? 0) > (estimate.max_rows ?? Infinity);
  const overUploadLimit =
    estimate != null &&
    includeUploads &&
    (estimate.uploads_bytes ?? 0) > (estimate.max_upload_bytes ?? Infinity);

  const startExport = () => {
    const includeParam: Record<string, boolean> = {};
    for (const tool of visibleTools) {
      includeParam[tool] = included(tool);
    }
    const params: Record<string, unknown> = {
      mode,
      include: JSON.stringify(includeParam),
    };
    if (scope === "initiative") {
      params.initiative_id = initiativeId;
    }
    if (mode === "backup") {
      params.include_uploads = includeUploads;
    } else {
      const formatParam: Record<string, unknown> = { document: documentFormats };
      for (const tool of visibleTools) {
        const options = REPORT_TOOL_FORMATS[tool];
        if (options) {
          formatParam[tool] = formats[tool] ?? options[0].format;
        }
      }
      params.formats = JSON.stringify(formatParam);
    }
    setStep("progress");
    void exportJob.start({
      endpoint: scope === "guild" ? "/exports/guild" : "/exports/initiative",
      params,
      fallbackFilename: `${scope}-export.zip`,
    });
  };

  const back = () => {
    if (step === "backup" || step === "report") {
      setStep("mode");
    } else if (step === "confirm") {
      setStep(mode === "backup" ? "backup" : "report");
    }
  };

  const stepDescription = useMemo(() => {
    switch (step) {
      case "mode":
        return t("wizard.mode.prompt");
      case "backup":
        return t("wizard.backup.prompt");
      case "report":
        return t("wizard.report.documentOthersNote");
      case "confirm":
        return t("wizard.confirm.prompt");
      case "progress":
        return null;
    }
  }, [step, t]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-lg overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {scope === "guild" ? t("wizard.titleGuild") : t("wizard.titleInitiative")}
          </DialogTitle>
          {stepDescription && <DialogDescription>{stepDescription}</DialogDescription>}
        </DialogHeader>

        {step !== "mode" && step !== "progress" && (
          <Button variant="ghost" size="sm" className="w-fit" onClick={back}>
            <ChevronLeft className="mr-1 h-4 w-4" />
            {t("wizard.back")}
          </Button>
        )}

        {step === "mode" && (
          <div className="space-y-2">
            {(["backup", "report"] as const).map((option) => (
              <button
                key={option}
                type="button"
                className="w-full rounded-lg border p-4 text-left transition-colors hover:bg-accent"
                onClick={() => {
                  setMode(option);
                  setStep(option);
                }}
              >
                <p className="font-medium text-sm">
                  {option === "backup"
                    ? t("wizard.mode.backupTitle")
                    : t("wizard.mode.reportTitle")}
                </p>
                <p className="mt-1 text-muted-foreground text-xs">
                  {option === "backup"
                    ? t("wizard.mode.backupDescription")
                    : t("wizard.mode.reportDescription")}
                </p>
              </button>
            ))}
          </div>
        )}

        {step === "backup" && (
          <div className="space-y-4">
            <div className="space-y-2">
              {visibleTools.map((tool) => {
                const disabled = toolDisabled(tool);
                const count = estimate?.tools?.[tool]?.count;
                return (
                  <div
                    key={tool}
                    className="flex items-center justify-between rounded-lg border p-3"
                  >
                    <div className="min-w-0">
                      <Label htmlFor={`include-${tool}`} className="text-sm">
                        {t(`nav:${toolNavLabelKey(tool)}` as never)}
                      </Label>
                      <p className="text-muted-foreground text-xs">
                        {disabled
                          ? t("wizard.backup.disabled")
                          : count != null
                            ? t("wizard.backup.toolCount", { count })
                            : " "}
                      </p>
                    </div>
                    <Switch
                      id={`include-${tool}`}
                      checked={!disabled && included(tool)}
                      disabled={disabled}
                      onCheckedChange={(checked) => setIncluded(tool, checked)}
                    />
                  </div>
                );
              })}
            </div>
            <div className="flex items-center justify-between rounded-lg border p-3">
              <div className="min-w-0">
                <Label htmlFor="include-uploads" className="text-sm">
                  {t("wizard.backup.includeUploads")}
                </Label>
                <p className="text-muted-foreground text-xs">
                  {estimateQuery.isError
                    ? t("wizard.backup.estimateFailed")
                    : estimate
                      ? t("wizard.backup.uploadsSize", {
                          size: formatBytes(estimate.uploads_bytes ?? 0),
                        })
                      : " "}
                </p>
              </div>
              <Switch
                id="include-uploads"
                checked={includeUploads}
                onCheckedChange={setIncludeUploads}
              />
            </div>
            {(overRowLimit || overUploadLimit) && (
              <div className="flex items-start gap-2 rounded-lg border border-destructive/50 bg-destructive/5 p-3 text-destructive text-sm">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>
                  {overUploadLimit
                    ? t("wizard.backup.overUploadLimit", {
                        limit: formatBytes(estimate?.max_upload_bytes ?? 0),
                      })
                    : t("wizard.backup.overRowLimit")}
                </span>
              </div>
            )}
            <Button
              className="w-full"
              disabled={overRowLimit || overUploadLimit}
              onClick={() => setStep("confirm")}
            >
              {t("wizard.next")}
            </Button>
          </div>
        )}

        {step === "report" && (
          <div className="space-y-4">
            <div className="space-y-2">
              {visibleTools.map((tool) => {
                const options = REPORT_TOOL_FORMATS[tool];
                const isDocuments = options == null;
                return (
                  <div key={tool} className="space-y-2 rounded-lg border p-3">
                    <div className="flex items-center justify-between">
                      <Label htmlFor={`report-${tool}`} className="text-sm">
                        {t(`nav:${toolNavLabelKey(tool)}` as never)}
                      </Label>
                      <Switch
                        id={`report-${tool}`}
                        checked={included(tool)}
                        onCheckedChange={(checked) => setIncluded(tool, checked)}
                      />
                    </div>
                    {included(tool) && !isDocuments && (
                      <RadioGroup
                        value={formats[tool] ?? options[0].format}
                        onValueChange={(value) =>
                          setFormats((prev) => ({ ...prev, [tool]: value }))
                        }
                        className="flex flex-wrap gap-3"
                      >
                        {options.map((option) => (
                          <div key={option.format} className="flex items-center gap-1.5">
                            <RadioGroupItem value={option.format} id={`${tool}-${option.format}`} />
                            <Label htmlFor={`${tool}-${option.format}`} className="text-xs">
                              {t(`tasks:${option.labelKey}` as never)}
                            </Label>
                          </div>
                        ))}
                      </RadioGroup>
                    )}
                    {included(tool) && isDocuments && (
                      <div className="space-y-2">
                        {(["native", "spreadsheet"] as const).map((docType) => (
                          <div key={docType} className="space-y-1">
                            <p className="text-muted-foreground text-xs">
                              {docType === "native"
                                ? t("wizard.report.documentNative")
                                : t("wizard.report.documentSpreadsheet")}
                            </p>
                            <RadioGroup
                              value={documentFormats[docType]}
                              onValueChange={(value) =>
                                setDocumentFormats((prev) => ({ ...prev, [docType]: value }))
                              }
                              className="flex flex-wrap gap-3"
                            >
                              {REPORT_DOCUMENT_FORMATS[docType].map((option) => (
                                <div key={option.format} className="flex items-center gap-1.5">
                                  <RadioGroupItem
                                    value={option.format}
                                    id={`doc-${docType}-${option.format}`}
                                  />
                                  <Label
                                    htmlFor={`doc-${docType}-${option.format}`}
                                    className="text-xs"
                                  >
                                    {t(`tasks:${option.labelKey}` as never)}
                                  </Label>
                                </div>
                              ))}
                            </RadioGroup>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
            <Button className="w-full" onClick={() => setStep("confirm")}>
              {t("wizard.next")}
            </Button>
          </div>
        )}

        {step === "confirm" && (
          <div className="space-y-4">
            <div className="space-y-1 rounded-lg border p-3 text-sm">
              <p className="font-medium">
                {mode === "backup"
                  ? t("wizard.confirm.modeBackup")
                  : t("wizard.confirm.modeReport")}
              </p>
              <p className="text-muted-foreground text-xs">
                {visibleTools
                  .filter((tool) => included(tool))
                  .map((tool) => t(`nav:${toolNavLabelKey(tool)}` as never))
                  .join(" · ")}
              </p>
              {mode === "backup" && (
                <p className="text-muted-foreground text-xs">
                  {includeUploads
                    ? t("wizard.confirm.uploadsIncluded")
                    : t("wizard.confirm.uploadsExcluded")}
                </p>
              )}
            </div>
            <p className="text-muted-foreground text-xs">{t("wizard.confirm.note")}</p>
            <Button className="w-full" onClick={startExport}>
              {t("wizard.start")}
            </Button>
          </div>
        )}

        {step === "progress" && (
          <div className="flex flex-col items-center gap-3 py-6 text-center">
            {exportJob.phase === "done" ? (
              <>
                <CheckCircle2 className="h-8 w-8 text-primary" />
                <p className="font-medium text-sm">{t("wizard.done.title")}</p>
                <p className="text-muted-foreground text-xs">{t("wizard.done.note")}</p>
              </>
            ) : exportJob.phase === "failed" ? (
              <>
                <XCircle className="h-8 w-8 text-destructive" />
                <p className="font-medium text-sm">{t("wizard.failed.title")}</p>
                <p className="text-muted-foreground text-xs">{t("wizard.failed.note")}</p>
              </>
            ) : (
              <>
                <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                <p className="font-medium text-sm">{t("wizard.progress.title")}</p>
                <p className="text-muted-foreground text-xs">{t("wizard.progress.note")}</p>
              </>
            )}
            <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
              {t("wizard.close")}
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
