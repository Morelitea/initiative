import { AlertTriangle, CheckCircle2, ChevronDown, Filter, Loader2, XCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { useEstimateAggregateExportApiV1CGuildIdExportsEstimateGet } from "@/api/generated/exports/exports";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import type { ExportExtraAction, ExportFormatOption } from "@/components/exports/ExportButton";
import {
  AGGREGATE_EXPORT_TOOLS,
  REPORT_DOCUMENT_FORMATS,
  REPORT_TOOL_FORMATS,
} from "@/components/exports/formats";
import {
  type ToolArchiveChoice,
  ToolArchiveFilter,
} from "@/components/initiativeTools/shared/ToolArchiveFilter";
import { FilterCountBadge } from "@/components/initiativeTools/shared/ToolFilterPanel";
import { ToolFilterFields, type ToolListFilters } from "@/components/tools/ToolFilterFields";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  DateRangeField,
  dateRangeParams,
  isDateRangeSet,
  type LocalDateRange,
  useFormatDateRange,
} from "@/components/ui/date-range-field";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Switch } from "@/components/ui/switch";
import { WizardDialog } from "@/components/ui/wizard-dialog";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useExportJob } from "@/hooks/useExportJob";
import { useWizard } from "@/hooks/useWizard";
import { formatBytes } from "@/lib/fileUtils";
import { toolExportEndpoint, toolNavLabelKey } from "@/lib/tools";
import { cn } from "@/lib/utils";

/** What the wizard exports: a whole initiative or community, or named
 *  entities of one tool (a tool's export card, a bulk selection). */
export type ExportWizardScope =
  | { kind: "initiative"; initiativeId: number }
  | { kind: "guild" }
  | {
      kind: "entities";
      tool: Tool;
      ids: number[];
      /** The formats on offer: json under "Backup", the rest under "Report". */
      formats: ExportFormatOption[];
      /** Inline-download filename stem: `{stem}.{format}`. */
      filenameStem: string;
      extraActions?: ExportExtraAction[];
    };

export interface ExportWizardProps {
  scope: ExportWizardScope;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type AggregateScope = Exclude<ExportWizardScope, { kind: "entities" }>;
type EntitiesScope = Extract<ExportWizardScope, { kind: "entities" }>;

const DEFAULT_DOCUMENT_FORMATS = { native: "pdf", spreadsheet: "xlsx" };

/** Tools whose content has a filter of its own, and the key it travels under
 *  in `filters`: a calendar's events, by date. */
const CONTENT_DATE_FILTERS: Partial<Record<Tool, "events">> = { [Tool.calendar]: "events" };

/** An export's `archived`: omitted exports live and archived alike. */
const ARCHIVED_FOR: Record<ToolArchiveChoice, boolean | undefined> = {
  all: undefined,
  active: false,
  archived: true,
};

const archiveChoice = (archived: boolean | null | undefined): ToolArchiveChoice =>
  archived == null ? "all" : archived ? "archived" : "active";

/** Drops what narrows nothing — blank text, empty lists and objects, unset
 *  values — so only real filters are sent. */
const compact = (filters: object): Record<string, unknown> =>
  Object.fromEntries(
    Object.entries(filters).flatMap(([key, raw]) => {
      const value: unknown = typeof raw === "string" ? raw.trim() : raw;
      const empty =
        value == null ||
        value === "" ||
        (Array.isArray(value) && value.length === 0) ||
        (typeof value === "object" && !Array.isArray(value) && Object.keys(value).length === 0);
      return empty ? [] : [[key, value]];
    })
  );

/** One tool's `filters` entry: its list filters, and its content filter. */
const toolExportFilters = (
  tool: Tool,
  listFilters: ToolListFilters | undefined,
  contentDates: LocalDateRange
): Record<string, unknown> => {
  const contentKey = CONTENT_DATE_FILTERS[tool];
  return compact({
    ...listFilters,
    ...(contentKey ? { [contentKey]: dateRangeParams(contentDates) } : {}),
  });
};

/** The wizard's step trail and its export job, reset to a fresh flow when the
 *  dialog closes (state only — a job already started keeps polling in the hook
 *  and delivers regardless). Re-opening while that job still renders resumes
 *  its progress view: the hook can't start a second job, so offering the
 *  option steps again would end in a "Start export" that silently tracked the
 *  OLD job. */
function useExportWizardFlow<S extends string>(open: boolean, first: S, resetState: () => void) {
  const exportJob = useExportJob();
  const wizard = useWizard<S | "progress">(first);

  // biome-ignore lint/correctness/useExhaustiveDependencies: runs only on open/close; job state is read at that moment, and reacting to every poll tick would re-fire the reset
  useEffect(() => {
    if (!open) {
      wizard.reset();
      resetState();
      exportJob.reset();
    } else if (exportJob.busy) {
      wizard.commit("progress");
    }
  }, [open]);

  return { ...wizard, exportJob };
}

/** The last step: the job's progress, then how it ended. */
function ExportProgress({
  phase,
  inline,
  onClose,
}: {
  phase: ReturnType<typeof useExportJob>["phase"];
  inline: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation("exports");
  return (
    <div className="flex flex-col items-center gap-3 py-6 text-center">
      {phase === "done" ? (
        <>
          <CheckCircle2 className="h-8 w-8 text-primary" />
          <p className="font-medium text-sm">{t("wizard.done.title")}</p>
          <p className="text-muted-foreground text-xs">
            {inline ? t("wizard.done.noteInline") : t("wizard.done.note")}
          </p>
        </>
      ) : phase === "failed" ? (
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
      <Button variant="outline" size="sm" onClick={onClose}>
        {t("wizard.close")}
      </Button>
    </div>
  );
}

/** The date range a tool's content is narrowed by — a calendar's events. */
function ContentDatesField({
  tool,
  value,
  onChange,
}: {
  tool: Tool;
  value: LocalDateRange;
  onChange: (next: LocalDateRange) => void;
}) {
  const { t } = useTranslation("exports");
  return (
    <div className="space-y-2">
      <Label htmlFor={`${tool}-content-dates`} className="text-xs">
        {t("wizard.filter.eventDates")}
      </Label>
      <DateRangeField id={`${tool}-content-dates`} value={value} onChange={onChange} />
    </div>
  );
}

/** A tool card's "Filter" disclosure: which of the tool's things to export
 *  (its list's own filters, plus live / archived / both), and what inside
 *  them where the content has a filter of its own. */
function ToolFilterSection({
  tool,
  value,
  onChange,
  contentDates,
  onContentDatesChange,
}: {
  tool: Tool;
  value: ToolListFilters;
  onChange: (next: ToolListFilters) => void;
  contentDates: LocalDateRange;
  onContentDatesChange: (next: LocalDateRange) => void;
}) {
  const { t } = useTranslation(["exports", "nav"]);
  const [open, setOpen] = useState(false);
  const count = Object.keys(toolExportFilters(tool, value, contentDates)).length;

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 gap-2 px-2"
          aria-label={t("wizard.filter.toggleFor", {
            tool: t(`nav:${toolNavLabelKey(tool)}` as never),
          })}
        >
          <Filter className="h-3.5 w-3.5" />
          {t("wizard.filter.toggle")}
          <FilterCountBadge count={count} />
          <ChevronDown className={cn("h-3 w-3 transition-transform", open && "rotate-180")} />
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent className="space-y-3 pt-2">
        <ToolArchiveFilter
          tool={tool}
          includeAll
          value={archiveChoice(value.archived)}
          onChange={(choice) => onChange({ ...value, archived: ARCHIVED_FOR[choice] })}
        />
        <div className="flex flex-col gap-3">
          <ToolFilterFields tool={tool} value={value} onChange={onChange} />
        </div>
        {CONTENT_DATE_FILTERS[tool] ? (
          <ContentDatesField tool={tool} value={contentDates} onChange={onContentDatesChange} />
        ) : null}
      </CollapsibleContent>
    </Collapsible>
  );
}

/** One tool's active filters, briefly: "1 Jul – 30 Sep 2026 · 2 tags". */
function useDescribeFilters() {
  const { t } = useTranslation("exports");
  const formatRange = useFormatDateRange();
  return (filters: Record<string, unknown>, contentDates: LocalDateRange): string => {
    const parts: string[] = [];
    if ("events" in filters) parts.push(formatRange(contentDates));
    if (typeof filters.search === "string") {
      parts.push(t("wizard.filterSummary.search", { search: filters.search }));
    }
    if (Array.isArray(filters.tag_ids)) {
      parts.push(t("wizard.filterSummary.tags", { count: filters.tag_ids.length }));
    }
    if (filters.archived === true) parts.push(t("wizard.filterSummary.archivedOnly"));
    if (filters.archived === false) parts.push(t("wizard.filterSummary.activeOnly"));
    const described = new Set(["events", "search", "tag_ids", "archived"]);
    const more = Object.keys(filters).filter((key) => !described.has(key)).length;
    if (more > 0) parts.push(t("wizard.filterSummary.more", { count: more }));
    return parts.join(" · ");
  };
}

/** The aggregate export flow: mode → (backup options with live estimate |
 * per-tool report formats), each tool with its filters → confirm → progress.
 * Delivery is the shared useExportJob poll — closing the dialog mid-render
 * doesn't cancel the job, the download still arrives (and lands in the
 * settings exports table). */
function AggregateExportWizard({
  scope,
  open,
  onOpenChange,
}: ExportWizardProps & { scope: AggregateScope }) {
  const { t } = useTranslation(["exports", "nav"]);
  const guildId = useActiveGuildId();
  const describeFilters = useDescribeFilters();

  const [mode, setMode] = useState<"backup" | "report">("backup");
  const [include, setInclude] = useState<Record<string, boolean>>({});
  const [includeUploads, setIncludeUploads] = useState(true);
  const [formats, setFormats] = useState<Record<string, string>>({});
  const [documentFormats, setDocumentFormats] = useState(DEFAULT_DOCUMENT_FORMATS);
  const [listFilters, setListFilters] = useState<Partial<Record<Tool, ToolListFilters>>>({});
  const [contentDates, setContentDates] = useState<LocalDateRange>({});

  const { step, go, commit, back, canGoBack, exportJob } = useExportWizardFlow<
    "mode" | "backup" | "report" | "confirm"
  >(open, "mode", () => {
    setMode("backup");
    setInclude({});
    setIncludeUploads(true);
    setFormats({});
    setDocumentFormats(DEFAULT_DOCUMENT_FORMATS);
    setListFilters({});
    setContentDates({});
  });

  const visibleTools = AGGREGATE_EXPORT_TOOLS;
  const included = (tool: Tool) => include[tool] !== false;
  const setIncluded = (tool: Tool, value: boolean) =>
    setInclude((prev) => ({ ...prev, [tool]: value }));

  // Each included tool's filters, and only the tools that have some; no
  // `filters` param at all when none do.
  const activeFilters = visibleTools.flatMap((tool) => {
    const filters = included(tool) ? toolExportFilters(tool, listFilters[tool], contentDates) : {};
    return Object.keys(filters).length > 0 ? [[tool, filters] as const] : [];
  });
  const filtersParam =
    activeFilters.length > 0 ? JSON.stringify(Object.fromEntries(activeFilters)) : undefined;
  // A keystroke in a search box is not a request.
  const estimateFilters = useDebouncedValue(filtersParam, 300);

  const estimateQuery = useEstimateAggregateExportApiV1CGuildIdExportsEstimateGet(
    guildId,
    {
      scope: scope.kind,
      initiative_id: scope.kind === "initiative" ? scope.initiativeId : null,
      include_uploads: includeUploads,
      ...(estimateFilters ? { filters: estimateFilters } : {}),
    },
    { query: { enabled: open && step === "backup" } }
  );
  const estimate = estimateQuery.data;
  // The numbers below describe the filters as they were when asked; until
  // they describe the current ones, the backup step waits for them.
  const estimateCurrent = estimateFilters === filtersParam && !estimateQuery.isFetching;

  const toolDisabled = (tool: Tool) => estimate?.tools?.[tool]?.disabled === true;

  const overRowLimit =
    estimate != null && (estimate.estimated_rows ?? 0) > (estimate.max_rows ?? Infinity);
  const overUploadLimit =
    estimate != null &&
    includeUploads &&
    (estimate.uploads_bytes ?? 0) > (estimate.max_upload_bytes ?? Infinity);
  // Past the download bound the archive is written to the server's export
  // folder instead of being handed back. Say which of the two will happen
  // before anybody starts a build that runs for an hour.
  const overDownloadBound =
    estimate != null &&
    !overUploadLimit &&
    (estimate.uploads_bytes ?? 0) > (estimate.max_download_bytes ?? Infinity);
  const deliveryAvailable = estimate?.delivery_available === true;
  const blockedForNoDestination = overDownloadBound && !deliveryAvailable;

  // A disabled tool's switch is locked showing "off" — the payload must say
  // the same (the backend would skip it anyway, but the manifest's
  // included/excluded/disabled inventory should match what the user saw).
  const effectiveIncluded = (tool: Tool) => !toolDisabled(tool) && included(tool);
  const anyIncluded = visibleTools.some(effectiveIncluded);

  const toolLabel = (tool: Tool) => t(`nav:${toolNavLabelKey(tool)}` as never);

  const filterSection = (tool: Tool) => (
    <ToolFilterSection
      tool={tool}
      value={listFilters[tool] ?? {}}
      onChange={(next) => setListFilters((prev) => ({ ...prev, [tool]: next }))}
      contentDates={contentDates}
      onContentDatesChange={setContentDates}
    />
  );

  const startExport = () => {
    if (exportJob.busy) {
      return;
    }
    const includeParam: Record<string, boolean> = {};
    for (const tool of visibleTools) {
      includeParam[tool] = effectiveIncluded(tool);
    }
    const params: Record<string, unknown> = {
      mode,
      include: JSON.stringify(includeParam),
      ...(filtersParam ? { filters: filtersParam } : {}),
    };
    if (scope.kind === "initiative") {
      params.initiative_id = scope.initiativeId;
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
    commit("progress");
    void exportJob.start({
      endpoint: scope.kind === "guild" ? "/exports/community" : "/exports/initiative",
      params,
      fallbackFilename: `${scope.kind}-export.zip`,
    });
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

  // Three questions, whichever way round you answer them: the backup options
  // and the report formats are the same position, one on each route.
  const position = { mode: 1, backup: 2, report: 2, confirm: 3, progress: null }[step];

  return (
    <WizardDialog
      open={open}
      onOpenChange={onOpenChange}
      className="max-h-[85vh] overflow-y-auto sm:max-w-lg"
      title={scope.kind === "guild" ? t("wizard.titleGuild") : t("wizard.titleInitiative")}
      description={stepDescription}
      progress={position === null ? undefined : { current: position, total: 3 }}
      onBack={canGoBack ? back : undefined}
      backLabel={t("wizard.back")}
    >
      {step === "mode" && (
        <div className="space-y-2">
          {(["backup", "report"] as const).map((option) => (
            <button
              key={option}
              type="button"
              className="w-full rounded-lg border p-4 text-left transition-colors hover:bg-accent"
              onClick={() => {
                setMode(option);
                go(option);
              }}
            >
              <p className="font-medium text-sm">
                {option === "backup" ? t("wizard.mode.backupTitle") : t("wizard.mode.reportTitle")}
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
                <fieldset
                  key={tool}
                  aria-label={toolLabel(tool)}
                  className="min-w-0 space-y-2 rounded-lg border p-3"
                >
                  <div className="flex items-center justify-between">
                    <div className="min-w-0">
                      <Label htmlFor={`include-${tool}`} className="text-sm">
                        {toolLabel(tool)}
                      </Label>
                      <p className="text-muted-foreground text-xs">
                        {disabled
                          ? t("wizard.backup.disabled")
                          : count != null
                            ? t("wizard.backup.toolCount", { count })
                            : " "}
                      </p>
                    </div>
                    <Switch
                      id={`include-${tool}`}
                      checked={!disabled && included(tool)}
                      disabled={disabled}
                      onCheckedChange={(checked) => setIncluded(tool, checked)}
                    />
                  </div>
                  {!disabled && included(tool) && filterSection(tool)}
                </fieldset>
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
                    : " "}
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
          {overDownloadBound && (
            <div
              className={
                blockedForNoDestination
                  ? "flex items-start gap-2 rounded-lg border border-destructive/50 bg-destructive/5 p-3 text-destructive text-sm"
                  : "flex items-start gap-2 rounded-lg border bg-muted/40 p-3 text-muted-foreground text-sm"
              }
            >
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>
                {blockedForNoDestination
                  ? t("wizard.backup.noDestination", {
                      limit: formatBytes(estimate?.max_download_bytes ?? 0),
                    })
                  : t("wizard.backup.willBeDelivered", {
                      limit: formatBytes(estimate?.max_download_bytes ?? 0),
                    })}
              </span>
            </div>
          )}
          <Button
            className="w-full"
            disabled={
              !estimateCurrent ||
              !anyIncluded ||
              overRowLimit ||
              overUploadLimit ||
              blockedForNoDestination
            }
            onClick={() => go("confirm")}
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
                <fieldset
                  key={tool}
                  aria-label={toolLabel(tool)}
                  className="min-w-0 space-y-2 rounded-lg border p-3"
                >
                  <div className="flex items-center justify-between">
                    <Label htmlFor={`report-${tool}`} className="text-sm">
                      {toolLabel(tool)}
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
                      onValueChange={(value) => setFormats((prev) => ({ ...prev, [tool]: value }))}
                      className="flex flex-wrap gap-3"
                    >
                      {options.map((option) => (
                        <div key={option.format} className="flex items-center gap-1.5">
                          <RadioGroupItem value={option.format} id={`${tool}-${option.format}`} />
                          <Label htmlFor={`${tool}-${option.format}`} className="text-xs">
                            {t(option.labelKey as never)}
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
                                  {t(option.labelKey as never)}
                                </Label>
                              </div>
                            ))}
                          </RadioGroup>
                        </div>
                      ))}
                    </div>
                  )}
                  {included(tool) && filterSection(tool)}
                </fieldset>
              );
            })}
          </div>
          <Button className="w-full" disabled={!anyIncluded} onClick={() => go("confirm")}>
            {t("wizard.next")}
          </Button>
        </div>
      )}

      {step === "confirm" && (
        <div className="space-y-4">
          <div className="space-y-1 rounded-lg border p-3 text-sm">
            <p className="font-medium">
              {mode === "backup" ? t("wizard.confirm.modeBackup") : t("wizard.confirm.modeReport")}
            </p>
            <p className="text-muted-foreground text-xs">
              {/* Same predicate as the submitted payload — a disabled
                    tool's locked-off switch must not reappear here. */}
              {visibleTools.filter(effectiveIncluded).map(toolLabel).join(" · ")}
            </p>
            {activeFilters
              .filter(([tool]) => effectiveIncluded(tool))
              .map(([tool, filters]) => (
                <p key={tool} className="text-muted-foreground text-xs">
                  {t("wizard.confirm.toolFilters", {
                    tool: toolLabel(tool),
                    filters: describeFilters(filters, contentDates),
                  })}
                </p>
              ))}
            {mode === "backup" && (
              <p className="text-muted-foreground text-xs">
                {includeUploads
                  ? t("wizard.confirm.uploadsIncluded")
                  : t("wizard.confirm.uploadsExcluded")}
              </p>
            )}
          </div>
          <p className="text-muted-foreground text-xs">{t("wizard.confirm.note")}</p>
          {/* busy guard: the hook can only track one job — starting while a
                previous job still polls would show its progress as this
                export's and deliver the wrong download. */}
          <Button className="w-full" disabled={exportJob.busy} onClick={startExport}>
            {t("wizard.start")}
          </Button>
        </div>
      )}

      {step === "progress" && (
        <ExportProgress
          phase={exportJob.phase}
          inline={exportJob.inline}
          onClose={() => onOpenChange(false)}
        />
      )}
    </WizardDialog>
  );
}

/** Exporting named entities of one tool: format → the tool's content filter
 * (skipped for a tool whose content has none) → confirm → progress. A small
 * export downloads straight away; a large one queues, as useExportJob does
 * for every surface. */
function EntitiesExportWizard({
  scope,
  open,
  onOpenChange,
}: ExportWizardProps & { scope: EntitiesScope }) {
  const { t } = useTranslation("exports");
  const formatRange = useFormatDateRange();
  const { tool, ids, formats, filenameStem, extraActions = [] } = scope;
  const contentKey = CONTENT_DATE_FILTERS[tool];

  // A tool with one format and nothing client-side has no choice to offer,
  // so the wizard starts past it.
  const only = formats.length === 1 && extraActions.length === 0 ? formats[0] : null;
  const [option, setOption] = useState<ExportFormatOption | null>(only);
  const [contentDates, setContentDates] = useState<LocalDateRange>({});

  const { step, go, commit, back, canGoBack, exportJob } = useExportWizardFlow<
    "format" | "content" | "confirm"
  >(open, only ? (contentKey ? "content" : "confirm") : "format", () => {
    setOption(only);
    setContentDates({});
  });

  // The menu's grouping, kept: the JSON envelope is the importable backup;
  // every other format, and the client-side extras, is a report.
  const backupFormats = formats.filter((format) => format.format === "json");
  const reportFormats = formats.filter((format) => format.format !== "json");

  const startExport = () => {
    if (exportJob.busy || !option) {
      return;
    }
    // Only the content key travels for named entities: the ids already say
    // which things.
    const filters = toolExportFilters(tool, undefined, contentDates);
    commit("progress");
    void exportJob.start({
      endpoint: toolExportEndpoint(tool),
      params: {
        ids,
        format: option.format,
        ...option.extraParams,
        ...(Object.keys(filters).length > 0 ? { filters: JSON.stringify(filters) } : {}),
      },
      fallbackFilename: `${option.filenameStem ?? filenameStem}.${option.format}`,
    });
  };

  const formatButton = (format: ExportFormatOption) => (
    <Button
      key={format.labelKey}
      variant="outline"
      className="w-full justify-start"
      onClick={() => {
        setOption(format);
        go(contentKey ? "content" : "confirm");
      }}
    >
      {t(format.labelKey as never)}
    </Button>
  );

  const stepDescription = {
    format: t("wizard.format.prompt"),
    content: t("wizard.content.prompt"),
    confirm: t("wizard.confirm.prompt"),
    progress: null,
  }[step];
  const steps = [...(only ? [] : ["format"]), ...(contentKey ? ["content"] : []), "confirm"];
  const total = steps.length;
  const position = step === "progress" ? null : steps.indexOf(step) + 1;

  return (
    <WizardDialog
      open={open}
      onOpenChange={onOpenChange}
      className="max-h-[85vh] overflow-y-auto sm:max-w-lg"
      title={t("wizard.titleEntities", { count: ids.length })}
      description={stepDescription}
      progress={position === null ? undefined : { current: position, total }}
      onBack={canGoBack ? back : undefined}
      backLabel={t("wizard.back")}
    >
      {step === "format" && (
        <div className="space-y-4">
          {backupFormats.length > 0 && (
            <div className="space-y-2">
              <p className="font-medium text-muted-foreground text-xs">
                {t("export.headingBackup")}
              </p>
              {backupFormats.map(formatButton)}
            </div>
          )}
          {(reportFormats.length > 0 || extraActions.length > 0) && (
            <div className="space-y-2">
              <p className="font-medium text-muted-foreground text-xs">
                {t("export.headingReport")}
              </p>
              {reportFormats.map(formatButton)}
              {extraActions.map((action) => (
                <Button
                  key={action.labelKey}
                  variant="outline"
                  className="w-full justify-start"
                  onClick={() => {
                    action.onSelect();
                    onOpenChange(false);
                  }}
                >
                  {t(action.labelKey as never)}
                </Button>
              ))}
            </div>
          )}
        </div>
      )}

      {step === "content" && (
        <div className="space-y-4">
          <ContentDatesField tool={tool} value={contentDates} onChange={setContentDates} />
          <p className="text-muted-foreground text-xs">{t("wizard.content.allDatesNote")}</p>
          <Button className="w-full" onClick={() => go("confirm")}>
            {t("wizard.next")}
          </Button>
        </div>
      )}

      {step === "confirm" && option && (
        <div className="space-y-4">
          <div className="space-y-1 rounded-lg border p-3 text-sm">
            <p className="font-medium">{t(option.labelKey as never)}</p>
            <p className="text-muted-foreground text-xs">
              {t("wizard.confirm.selected", { count: ids.length })}
            </p>
            {contentKey && isDateRangeSet(contentDates) ? (
              <p className="text-muted-foreground text-xs">{formatRange(contentDates)}</p>
            ) : null}
          </div>
          <Button className="w-full" disabled={exportJob.busy} onClick={startExport}>
            {t("wizard.start")}
          </Button>
        </div>
      )}

      {step === "progress" && (
        <ExportProgress
          phase={exportJob.phase}
          inline={exportJob.inline}
          onClose={() => onOpenChange(false)}
        />
      )}
    </WizardDialog>
  );
}

/** The export wizard, for every scope: an initiative, the community, or named
 *  entities of one tool. */
export function ExportWizard({ scope, ...props }: ExportWizardProps) {
  return scope.kind === "entities" ? (
    <EntitiesExportWizard scope={scope} {...props} />
  ) : (
    <AggregateExportWizard scope={scope} {...props} />
  );
}
