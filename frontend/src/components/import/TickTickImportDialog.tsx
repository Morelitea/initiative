import { useState, useCallback, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Upload, FileText, CheckCircle2, AlertCircle } from "lucide-react";

import { useAuth } from "@/hooks/useAuth";
import { useParseTickTickCsv, useImportFromTickTick } from "@/hooks/useImports";
import { useProjects, useProjectTaskStatuses } from "@/hooks/useProjects";
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
import { Textarea } from "@/components/ui/textarea";
import type { TaskStatusRead } from "@/api/generated/initiativeAPI.schemas";
import type { DialogProps } from "@/types/dialog";

interface TickTickColumn {
  name: string;
  task_count: number;
}

interface TickTickList {
  name: string;
  task_count: number;
  columns: TickTickColumn[];
}

interface TickTickParseResult {
  lists: TickTickList[];
  total_tasks: number;
}

interface ImportResult {
  tasks_created: number;
  subtasks_created: number;
  tasks_failed: number;
  errors: string[];
}

type TickTickImportDialogProps = DialogProps;

type Step = "upload" | "select-list" | "configure" | "result";

// Suggest a status based on column name
const suggestStatusForColumn = (
  columnName: string,
  statuses: TaskStatusRead[]
): number | undefined => {
  const lowerName = columnName.toLowerCase();

  const categoryMapping: Record<string, string[]> = {
    backlog: ["backlog", "inbox", "later", "someday", "no column"],
    todo: ["to do", "todo", "to-do", "planned", "next"],
    in_progress: ["in progress", "doing", "working", "active", "current"],
    done: ["done", "complete", "completed", "finished"],
  };

  for (const [category, keywords] of Object.entries(categoryMapping)) {
    if (keywords.some((keyword) => lowerName.includes(keyword))) {
      const matchingStatus = statuses.find((s) => s.category === category);
      if (matchingStatus) {
        return matchingStatus.id;
      }
    }
  }

  return statuses[0]?.id;
};

export const TickTickImportDialog = ({ open, onOpenChange }: TickTickImportDialogProps) => {
  const { t } = useTranslation("import");
  const { user } = useAuth();
  const [step, setStep] = useState<Step>("upload");
  const [csvContent, setCsvContent] = useState("");
  const [parseResult, setParseResult] = useState<TickTickParseResult | null>(null);
  const [selectedSourceListName, setSelectedSourceListName] = useState<string | null>(null);
  const [selectedTargetProjectId, setSelectedTargetProjectId] = useState<number | null>(null);
  const [columnMapping, setColumnMapping] = useState<Record<string, number>>({});
  const [importResult, setImportResult] = useState<ImportResult | null>(null);

  // Reset state when dialog closes
  useEffect(() => {
    if (!open) {
      setStep("upload");
      setCsvContent("");
      setParseResult(null);
      setSelectedSourceListName(null);
      setSelectedTargetProjectId(null);
      setColumnMapping({});
      setImportResult(null);
    }
  }, [open]);

  // Fetch projects for selection
  const projectsQuery = useProjects(undefined, { enabled: open });

  // Fetch task statuses for selected target project
  const taskStatusesQuery = useProjectTaskStatuses(selectedTargetProjectId);

  // Get selected source list
  const selectedSourceList = parseResult?.lists.find((l) => l.name === selectedSourceListName);

  // Initialize column mapping when statuses load
  useEffect(() => {
    if (selectedSourceList && taskStatusesQuery.data) {
      const newMapping: Record<string, number> = {};
      for (const column of selectedSourceList.columns) {
        const suggestedId = suggestStatusForColumn(column.name, taskStatusesQuery.data);
        if (suggestedId !== undefined) {
          newMapping[column.name] = suggestedId;
        }
      }
      setColumnMapping(newMapping);
    }
  }, [selectedSourceList, taskStatusesQuery.data]);

  // Parse CSV mutation
  const parseMutation = useParseTickTickCsv({
    onSuccess: (data) => {
      const result = data as TickTickParseResult;
      setParseResult(result);
      if (result.lists.length === 0) {
        toast.error(t("ticktick.noListsFound"));
      } else {
        setStep("select-list");
      }
    },
    onError: () => {
      toast.error(t("ticktick.parseFailed"));
    },
  });

  // Import mutation
  const importMutation = useImportFromTickTick({
    onSuccess: (data) => {
      setImportResult(data as ImportResult);
      setStep("result");
    },
    onError: () => {
      toast.error(t("common.importFailed"));
    },
  });

  const handleFileUpload = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0];
      if (!file) return;

      const reader = new FileReader();
      reader.onload = (e) => {
        const content = e.target?.result as string;
        setCsvContent(content);
        parseMutation.mutate(content);
      };
      reader.readAsText(file);
    },
    [parseMutation]
  );

  const handlePasteContent = useCallback(() => {
    if (csvContent.trim()) {
      parseMutation.mutate(csvContent);
    }
  }, [csvContent, parseMutation]);

  const handleSelectSourceList = useCallback(() => {
    if (selectedSourceListName && selectedTargetProjectId) {
      setStep("configure");
    }
  }, [selectedSourceListName, selectedTargetProjectId]);

  const handleImport = useCallback(() => {
    if (!selectedTargetProjectId || !selectedSourceListName) return;
    importMutation.mutate({
      project_id: selectedTargetProjectId,
      csv_content: csvContent,
      source_list_name: selectedSourceListName,
      column_mapping: columnMapping,
    });
  }, [importMutation, selectedTargetProjectId, selectedSourceListName, csvContent, columnMapping]);

  // Filter to only show projects where user has write or owner permission
  const activeProjects =
    projectsQuery.data?.items?.filter((p) => {
      if (p.is_archived || p.is_template) return false;
      const userPermission = p.permissions?.find((perm) => perm.user_id === user?.id);
      return userPermission?.level === "owner" || userPermission?.level === "write";
    }) ?? [];
  const statuses = taskStatusesQuery.data ?? [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("ticktick.title")}</DialogTitle>
          <DialogDescription>
            {step === "upload" && t("ticktick.stepUploadDescription")}
            {step === "select-list" && t("ticktick.stepSelectListDescription")}
            {step === "configure" && t("ticktick.stepConfigureDescription")}
            {step === "result" && t("common.resultTitle")}
          </DialogDescription>
        </DialogHeader>

        {step === "upload" && (
          <div className="space-y-4">
            <div>
              <Label>{t("ticktick.uploadFileLabel")}</Label>
              <div className="mt-2">
                <label className="border-muted hover:bg-accent flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed p-6 transition-colors">
                  <Upload className="text-muted-foreground mb-2 h-8 w-8" />
                  <span className="text-muted-foreground text-sm">
                    {t("common.uploadDragDrop")}
                  </span>
                  <span className="text-muted-foreground mt-1 text-xs">
                    {t("ticktick.uploadHint")}
                  </span>
                  <input type="file" accept=".csv" className="hidden" onChange={handleFileUpload} />
                </label>
              </div>
            </div>

            <div className="text-muted-foreground text-center text-sm">{t("common.or")}</div>

            <div>
              <Label htmlFor="csv-content">{t("ticktick.pasteLabel")}</Label>
              <Textarea
                id="csv-content"
                placeholder={t("ticktick.csvPlaceholder")}
                value={csvContent}
                onChange={(e) => setCsvContent(e.target.value)}
                className="mt-2 h-32 font-mono text-xs"
              />
              <Button
                variant="outline"
                size="sm"
                className="mt-2"
                onClick={handlePasteContent}
                disabled={!csvContent.trim() || parseMutation.isPending}
              >
                {parseMutation.isPending ? t("common.parsing") : t("common.parseContent")}
              </Button>
            </div>

            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => onOpenChange(false)}>
                {t("common.cancel")}
              </Button>
            </div>
          </div>
        )}

        {step === "select-list" && parseResult && (
          <div className="space-y-4">
            <div className="bg-muted rounded-lg p-4">
              <div className="flex items-center gap-2">
                <FileText className="h-4 w-4" />
                <span className="font-medium">{t("ticktick.exportParsed")}</span>
              </div>
              <p className="text-muted-foreground mt-1 text-sm">
                {t("ticktick.totalTasks", {
                  listCount: parseResult.lists.length,
                  listLabel: t("ticktick.listsDetected", { count: parseResult.lists.length })
                    .split(" ")
                    .slice(1)
                    .join(" "),
                  taskCount: parseResult.total_tasks,
                })}
              </p>
            </div>

            <div>
              <Label>{t("ticktick.importFromList")}</Label>
              <Select
                value={selectedSourceListName ?? ""}
                onValueChange={(value) => setSelectedSourceListName(value)}
              >
                <SelectTrigger className="mt-2">
                  <SelectValue placeholder={t("ticktick.selectListPlaceholder")} />
                </SelectTrigger>
                <SelectContent className="max-h-60">
                  {parseResult.lists.map((list) => (
                    <SelectItem key={list.name} value={list.name}>
                      {list.name} ({t("ticktick.tasksCount", { count: list.task_count })})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label>{t("common.importToInitiativeProject")}</Label>
              <Select
                value={selectedTargetProjectId?.toString() ?? ""}
                onValueChange={(value) => setSelectedTargetProjectId(Number(value))}
              >
                <SelectTrigger className="mt-2">
                  <SelectValue placeholder={t("common.selectProject")} />
                </SelectTrigger>
                <SelectContent className="max-h-60">
                  {activeProjects.map((project) => (
                    <SelectItem key={project.id} value={project.id.toString()}>
                      {project.icon && <span className="mr-2">{project.icon}</span>}
                      {project.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setStep("upload")}>
                {t("common.back")}
              </Button>
              <Button
                onClick={handleSelectSourceList}
                disabled={!selectedSourceListName || !selectedTargetProjectId}
              >
                {t("common.next")}
              </Button>
            </div>
          </div>
        )}

        {step === "configure" && selectedSourceList && (
          <div className="space-y-4">
            <div>
              <Label>{t("ticktick.mapColumnsLabel")}</Label>
              <p className="text-muted-foreground text-sm">{t("ticktick.mapColumnsDescription")}</p>
            </div>

            <div className="space-y-3">
              {selectedSourceList.columns.map((column) => (
                <div key={column.name} className="flex items-center justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">{column.name}</p>
                    <p className="text-muted-foreground text-xs">
                      {t("ticktick.taskCount", { count: column.task_count })}
                    </p>
                  </div>
                  <Select
                    value={columnMapping[column.name]?.toString() ?? ""}
                    onValueChange={(value) =>
                      setColumnMapping((prev) => ({
                        ...prev,
                        [column.name]: Number(value),
                      }))
                    }
                  >
                    <SelectTrigger className="w-40">
                      <SelectValue placeholder={t("common.selectStatus")} />
                    </SelectTrigger>
                    <SelectContent>
                      {statuses.map((status) => (
                        <SelectItem key={status.id} value={status.id.toString()}>
                          {status.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              ))}
            </div>

            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setStep("select-list")}>
                {t("common.back")}
              </Button>
              <Button
                onClick={handleImport}
                disabled={
                  importMutation.isPending ||
                  Object.keys(columnMapping).length !== selectedSourceList.columns.length
                }
              >
                {importMutation.isPending ? t("common.importing") : t("common.import")}
              </Button>
            </div>
          </div>
        )}

        {step === "result" && importResult && (
          <div className="space-y-4">
            <div
              className={`flex items-center gap-3 rounded-lg p-4 ${
                importResult.tasks_failed === 0 ? "bg-green-500/10" : "bg-yellow-500/10"
              }`}
            >
              {importResult.tasks_failed === 0 ? (
                <CheckCircle2 className="h-8 w-8 text-green-500" />
              ) : (
                <AlertCircle className="h-8 w-8 text-yellow-500" />
              )}
              <div>
                <p className="font-medium">
                  {importResult.tasks_failed === 0
                    ? t("common.importSuccessful")
                    : t("common.importWarnings")}
                </p>
                <p className="text-muted-foreground text-sm">
                  {t("common.tasksCreated", { count: importResult.tasks_created })}
                  {importResult.subtasks_created > 0 &&
                    `, ${t("common.subtasksCount", { count: importResult.subtasks_created })}`}
                  {importResult.tasks_failed > 0 &&
                    `, ${t("common.failedCount", { count: importResult.tasks_failed })}`}
                </p>
              </div>
            </div>

            {importResult.errors.length > 0 && (
              <div className="bg-muted max-h-40 overflow-y-auto rounded-lg p-3">
                <p className="mb-2 text-sm font-medium">{t("common.errors")}</p>
                <ul className="text-muted-foreground space-y-1 text-xs">
                  {importResult.errors.map((error, index) => (
                    <li key={index}>{error}</li>
                  ))}
                </ul>
              </div>
            )}

            <div className="flex justify-end">
              <Button onClick={() => onOpenChange(false)}>{t("common.done")}</Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
};
