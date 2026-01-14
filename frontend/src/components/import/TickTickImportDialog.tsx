import { useState, useCallback, useEffect } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Upload, FileText, CheckCircle2, AlertCircle } from "lucide-react";

import { apiClient } from "@/api/client";
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
import { queryClient } from "@/lib/queryClient";
import type { Project, ProjectTaskStatus } from "@/types/api";

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

interface TickTickImportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type Step = "upload" | "select-list" | "configure" | "result";

// Suggest a status based on column name
const suggestStatusForColumn = (
  columnName: string,
  statuses: ProjectTaskStatus[]
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
  const projectsQuery = useQuery<Project[]>({
    queryKey: ["projects"],
    queryFn: async () => {
      const response = await apiClient.get<Project[]>("/projects/");
      return response.data;
    },
    enabled: open,
  });

  // Fetch task statuses for selected target project
  const taskStatusesQuery = useQuery<ProjectTaskStatus[]>({
    queryKey: ["projects", selectedTargetProjectId, "task-statuses"],
    queryFn: async () => {
      const response = await apiClient.get<ProjectTaskStatus[]>(
        `/projects/${selectedTargetProjectId}/task-statuses/`
      );
      return response.data;
    },
    enabled: selectedTargetProjectId !== null,
  });

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
  const parseMutation = useMutation({
    mutationFn: async (content: string) => {
      const response = await apiClient.post<TickTickParseResult>(
        "/imports/ticktick/parse",
        content,
        { headers: { "Content-Type": "text/plain" } }
      );
      return response.data;
    },
    onSuccess: (data) => {
      setParseResult(data);
      if (data.lists.length === 0) {
        toast.error("No lists with tasks found in the export");
      } else {
        setStep("select-list");
      }
    },
    onError: () => {
      toast.error("Failed to parse CSV file");
    },
  });

  // Import mutation
  const importMutation = useMutation({
    mutationFn: async () => {
      if (!selectedTargetProjectId) throw new Error("No target project selected");
      if (!selectedSourceListName) throw new Error("No source list selected");
      const response = await apiClient.post<ImportResult>("/imports/ticktick", {
        project_id: selectedTargetProjectId,
        csv_content: csvContent,
        source_list_name: selectedSourceListName,
        column_mapping: columnMapping,
      });
      return response.data;
    },
    onSuccess: (data) => {
      setImportResult(data);
      setStep("result");
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      queryClient.invalidateQueries({ queryKey: ["project", selectedTargetProjectId] });
    },
    onError: () => {
      toast.error("Import failed");
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
    importMutation.mutate();
  }, [importMutation]);

  const activeProjects = projectsQuery.data?.filter((p) => !p.is_archived && !p.is_template) ?? [];
  const statuses = taskStatusesQuery.data ?? [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Import from TickTick</DialogTitle>
          <DialogDescription>
            {step === "upload" && "Upload your TickTick CSV export file or paste the content."}
            {step === "select-list" && "Select which list to import from and where to import to."}
            {step === "configure" && "Map TickTick columns to project statuses."}
            {step === "result" && "Import complete."}
          </DialogDescription>
        </DialogHeader>

        {step === "upload" && (
          <div className="space-y-4">
            <div>
              <Label>Upload CSV file</Label>
              <div className="mt-2">
                <label className="border-muted hover:bg-accent flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed p-6 transition-colors">
                  <Upload className="text-muted-foreground mb-2 h-8 w-8" />
                  <span className="text-muted-foreground text-sm">
                    Click to upload or drag and drop
                  </span>
                  <span className="text-muted-foreground mt-1 text-xs">
                    Export from TickTick Settings → Backup
                  </span>
                  <input type="file" accept=".csv" className="hidden" onChange={handleFileUpload} />
                </label>
              </div>
            </div>

            <div className="text-muted-foreground text-center text-sm">or</div>

            <div>
              <Label htmlFor="csv-content">Paste CSV content</Label>
              <Textarea
                id="csv-content"
                placeholder="Paste your TickTick CSV export here..."
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
                {parseMutation.isPending ? "Parsing..." : "Parse content"}
              </Button>
            </div>

            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
            </div>
          </div>
        )}

        {step === "select-list" && parseResult && (
          <div className="space-y-4">
            <div className="bg-muted rounded-lg p-4">
              <div className="flex items-center gap-2">
                <FileText className="h-4 w-4" />
                <span className="font-medium">Export parsed successfully</span>
              </div>
              <p className="text-muted-foreground mt-1 text-sm">
                Found {parseResult.lists.length} list
                {parseResult.lists.length === 1 ? "" : "s"} with {parseResult.total_tasks} total
                tasks
              </p>
            </div>

            <div>
              <Label>Import from TickTick list</Label>
              <Select
                value={selectedSourceListName ?? ""}
                onValueChange={(value) => setSelectedSourceListName(value)}
              >
                <SelectTrigger className="mt-2">
                  <SelectValue placeholder="Select a TickTick list" />
                </SelectTrigger>
                <SelectContent className="max-h-60">
                  {parseResult.lists.map((list) => (
                    <SelectItem key={list.name} value={list.name}>
                      {list.name} ({list.task_count} tasks)
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label>Import to Initiative project</Label>
              <Select
                value={selectedTargetProjectId?.toString() ?? ""}
                onValueChange={(value) => setSelectedTargetProjectId(Number(value))}
              >
                <SelectTrigger className="mt-2">
                  <SelectValue placeholder="Select a project" />
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
                Back
              </Button>
              <Button
                onClick={handleSelectSourceList}
                disabled={!selectedSourceListName || !selectedTargetProjectId}
              >
                Next
              </Button>
            </div>
          </div>
        )}

        {step === "configure" && selectedSourceList && (
          <div className="space-y-4">
            <div>
              <Label>Map columns to statuses</Label>
              <p className="text-muted-foreground text-sm">
                Choose which project status each TickTick column should map to.
              </p>
            </div>

            <div className="space-y-3">
              {selectedSourceList.columns.map((column) => (
                <div key={column.name} className="flex items-center justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">{column.name}</p>
                    <p className="text-muted-foreground text-xs">
                      {column.task_count} task{column.task_count === 1 ? "" : "s"}
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
                      <SelectValue placeholder="Select status" />
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
                Back
              </Button>
              <Button
                onClick={handleImport}
                disabled={
                  importMutation.isPending ||
                  Object.keys(columnMapping).length !== selectedSourceList.columns.length
                }
              >
                {importMutation.isPending ? "Importing..." : "Import"}
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
                    ? "Import successful!"
                    : "Import completed with warnings"}
                </p>
                <p className="text-muted-foreground text-sm">
                  {importResult.tasks_created} task{importResult.tasks_created === 1 ? "" : "s"}{" "}
                  created
                  {importResult.subtasks_created > 0 &&
                    `, ${importResult.subtasks_created} subtask${importResult.subtasks_created === 1 ? "" : "s"}`}
                  {importResult.tasks_failed > 0 && `, ${importResult.tasks_failed} failed`}
                </p>
              </div>
            </div>

            {importResult.errors.length > 0 && (
              <div className="bg-muted max-h-40 overflow-y-auto rounded-lg p-3">
                <p className="mb-2 text-sm font-medium">Errors:</p>
                <ul className="text-muted-foreground space-y-1 text-xs">
                  {importResult.errors.map((error, index) => (
                    <li key={index}>{error}</li>
                  ))}
                </ul>
              </div>
            )}

            <div className="flex justify-end">
              <Button onClick={() => onOpenChange(false)}>Done</Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
};
