import { useState, useCallback, useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Upload, FileText, CheckCircle2, AlertCircle } from "lucide-react";

import { useInitiatives } from "@/hooks/useInitiatives";
import { useAuth } from "@/hooks/useAuth";
import { apiMutator } from "@/api/mutator";
import { invalidateAllCalendarEvents } from "@/api/query-keys";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { DialogProps } from "@/types/dialog";

interface ICalEventPreview {
  summary: string;
  start_at: string;
  end_at: string | null;
  all_day: boolean;
  has_recurrence: boolean;
}

interface ICalParseResult {
  event_count: number;
  events: ICalEventPreview[];
  has_recurring: boolean;
}

interface ICalImportResult {
  events_created: number;
  events_failed: number;
  errors: string[];
}

type Step = "upload" | "result";

interface ICalImportDialogProps extends DialogProps {
  fixedInitiativeId?: number;
}

export const ICalImportDialog = ({
  open,
  onOpenChange,
  fixedInitiativeId,
}: ICalImportDialogProps) => {
  const { t } = useTranslation(["events", "common"]);
  const { user } = useAuth();

  const [step, setStep] = useState<Step>("upload");
  const [icsContent, setIcsContent] = useState("");
  const [selectedInitiativeId, setSelectedInitiativeId] = useState<number | null>(
    fixedInitiativeId ?? null
  );
  const [parseResult, setParseResult] = useState<ICalParseResult | null>(null);
  const [importResult, setImportResult] = useState<ICalImportResult | null>(null);
  const [isParsing, setIsParsing] = useState(false);
  const [isImporting, setIsImporting] = useState(false);

  useEffect(() => {
    if (!open) {
      setStep("upload");
      setIcsContent("");
      setSelectedInitiativeId(fixedInitiativeId ?? null);
      setParseResult(null);
      setImportResult(null);
    }
  }, [open, fixedInitiativeId]);

  const initiativesQuery = useInitiatives({ enabled: open });
  const creatableInitiatives = useMemo(() => {
    if (!user) return [];
    return (initiativesQuery.data ?? []).filter(
      (init) =>
        init.events_enabled &&
        init.members.some((m) => m.user.id === user.id && m.role === "project_manager")
    );
  }, [initiativesQuery.data, user]);

  const handleFileUpload = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (e) => {
        const content = e.target?.result as string;
        setIcsContent(content);
        doParse(content);
      };
      reader.readAsText(file);
    },
    [] // eslint-disable-line react-hooks/exhaustive-deps
  );

  const doParse = async (content: string) => {
    setIsParsing(true);
    try {
      const result = await apiMutator<ICalParseResult>({
        url: "/api/v1/calendar-events/import/parse",
        method: "POST",
        data: { initiative_id: selectedInitiativeId ?? 0, ics_content: content },
        headers: { "Content-Type": "application/json" },
      });
      setParseResult(result);
    } catch {
      toast.error(t("events:import.parseFailed"));
    } finally {
      setIsParsing(false);
    }
  };

  const handleImport = useCallback(async () => {
    if (!selectedInitiativeId || !icsContent) return;
    setIsImporting(true);
    try {
      const result = await apiMutator<ICalImportResult>({
        url: "/api/v1/calendar-events/import",
        method: "POST",
        data: { initiative_id: selectedInitiativeId, ics_content: icsContent },
        headers: { "Content-Type": "application/json" },
      });
      setImportResult(result);
      setStep("result");
      void invalidateAllCalendarEvents();
    } catch {
      toast.error(t("events:import.importError"));
    } finally {
      setIsImporting(false);
    }
  }, [selectedInitiativeId, icsContent, t]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("events:import.title")}</DialogTitle>
          <DialogDescription>{t("events:import.uploadDescription")}</DialogDescription>
        </DialogHeader>

        {step === "upload" && (
          <div className="space-y-4">
            <div>
              <Label>{t("events:import.uploadFileLabel")}</Label>
              <div className="mt-2">
                <label className="border-muted hover:bg-accent flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed p-6 transition-colors">
                  <Upload className="text-muted-foreground mb-2 h-8 w-8" />
                  <span className="text-muted-foreground text-sm">
                    {isParsing ? t("events:import.parsing") : t("events:import.uploadFileLabel")}
                  </span>
                  <input
                    type="file"
                    accept=".ics,.ical"
                    className="hidden"
                    onChange={handleFileUpload}
                  />
                </label>
              </div>
            </div>

            {parseResult && (
              <div className="bg-muted rounded-lg p-4">
                <div className="flex items-center gap-2">
                  <FileText className="h-4 w-4" />
                  <span className="font-medium">
                    {t("events:import.foundEvents", { count: parseResult.event_count })}
                  </span>
                </div>
                {parseResult.has_recurring && (
                  <p className="text-muted-foreground mt-1 text-sm">
                    {t("events:import.hasRecurring")}
                  </p>
                )}
                <ul className="text-muted-foreground mt-2 max-h-40 space-y-1 overflow-y-auto text-sm">
                  {parseResult.events.slice(0, 20).map((ev, i) => (
                    <li key={i} className="truncate">
                      {ev.summary}
                    </li>
                  ))}
                  {parseResult.events.length > 20 && (
                    <li className="italic">
                      {}
                      {`+${parseResult.events.length - 20}`}
                    </li>
                  )}
                </ul>
              </div>
            )}

            {parseResult && !fixedInitiativeId && (
              <div>
                <Label>{t("events:import.selectInitiative")}</Label>
                <Select
                  value={selectedInitiativeId?.toString() ?? ""}
                  onValueChange={(v) => setSelectedInitiativeId(Number(v))}
                >
                  <SelectTrigger className="mt-2">
                    <SelectValue placeholder={t("events:import.selectInitiative")} />
                  </SelectTrigger>
                  <SelectContent>
                    {creatableInitiatives.map((init) => (
                      <SelectItem key={init.id} value={init.id.toString()}>
                        {init.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => onOpenChange(false)}>
                {t("common:cancel")}
              </Button>
              <Button
                onClick={handleImport}
                disabled={!parseResult || !selectedInitiativeId || isImporting}
              >
                {isImporting ? t("events:import.importing") : t("events:import.importButton")}
              </Button>
            </div>
          </div>
        )}

        {step === "result" && importResult && (
          <div className="space-y-4">
            <div
              className={`flex items-center gap-3 rounded-lg p-4 ${
                importResult.events_failed === 0 ? "bg-green-500/10" : "bg-yellow-500/10"
              }`}
            >
              {importResult.events_failed === 0 ? (
                <CheckCircle2 className="h-8 w-8 text-green-500" />
              ) : (
                <AlertCircle className="h-8 w-8 text-yellow-500" />
              )}
              <div>
                <p className="font-medium">{t("events:import.importSuccess")}</p>
                <p className="text-muted-foreground text-sm">
                  {t("events:import.eventsCreated", {
                    count: importResult.events_created,
                  })}
                  {importResult.events_failed > 0 &&
                    `, ${t("events:import.eventsFailed", { count: importResult.events_failed })}`}
                </p>
              </div>
            </div>

            {importResult.errors.length > 0 && (
              <div className="bg-muted max-h-40 overflow-y-auto rounded-lg p-3">
                <ul className="text-muted-foreground space-y-1 text-xs">
                  {importResult.errors.map((error, i) => (
                    <li key={i}>{error}</li>
                  ))}
                </ul>
              </div>
            )}

            <div className="flex justify-end">
              <Button onClick={() => onOpenChange(false)}>{t("common:done")}</Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
};
