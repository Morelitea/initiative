import { useState, useCallback, useEffect } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Upload, FileText, CheckCircle2, AlertCircle } from "lucide-react";

import { apiClient } from "@/api/client";
import { useAuth } from "@/hooks/useAuth";
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

interface TodoistParseResult {
  sections: Array<{ name: string; task_count: number }>;
  task_count: number;
  has_subtasks: boolean;
}

interface ImportResult {
  tasks_created: number;
  subtasks_created: number;
  tasks_failed: number;
  errors: string[];
}

interface TodoistImportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type Step = "upload" | "configure" | "result";

// Suggest a status based on section name
const suggestStatusForSection = (
  sectionName: string,
  statuses: ProjectTaskStatus[]
): number | undefined => {
  const lowerName = sectionName.toLowerCase();

  // Map common section names to status categories
  const categoryMapping: Record<string, string[]> = {
    backlog: ["unassigned", "backlog", "inbox", "later", "someday"],
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

  // Default to first status
  return statuses[0]?.id;
};

export const TodoistImportDialog = ({ open, onOpenChange }: TodoistImportDialogProps) => {
  const { user } = useAuth();
  const [step, setStep] = useState<Step>("upload");
  const [csvContent, setCsvContent] = useState("");
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null);
  const [parseResult, setParseResult] = useState<TodoistParseResult | null>(null);
  const [sectionMapping, setSectionMapping] = useState<Record<string, number>>({});
  const [importResult, setImportResult] = useState<ImportResult | null>(null);

  // Reset state when dialog closes
  useEffect(() => {
    if (!open) {
      setStep("upload");
      setCsvContent("");
      setSelectedProjectId(null);
      setParseResult(null);
      setSectionMapping({});
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

  // Fetch task statuses for selected project
  const taskStatusesQuery = useQuery<ProjectTaskStatus[]>({
    queryKey: ["projects", selectedProjectId, "task-statuses"],
    queryFn: async () => {
      const response = await apiClient.get<ProjectTaskStatus[]>(
        `/projects/${selectedProjectId}/task-statuses/`
      );
      return response.data;
    },
    enabled: selectedProjectId !== null,
  });

  // Initialize section mapping when statuses load
  useEffect(() => {
    if (parseResult && taskStatusesQuery.data) {
      const newMapping: Record<string, number> = {};
      for (const section of parseResult.sections) {
        const suggestedId = suggestStatusForSection(section.name, taskStatusesQuery.data);
        if (suggestedId !== undefined) {
          newMapping[section.name] = suggestedId;
        }
      }
      setSectionMapping(newMapping);
    }
  }, [parseResult, taskStatusesQuery.data]);

  // Parse CSV mutation
  const parseMutation = useMutation({
    mutationFn: async (content: string) => {
      const response = await apiClient.post<TodoistParseResult>("/imports/todoist/parse", content, {
        headers: { "Content-Type": "text/plain" },
      });
      return response.data;
    },
    onSuccess: (data) => {
      setParseResult(data);
      if (data.sections.length === 0) {
        toast.error("No sections found in the CSV");
      }
    },
    onError: () => {
      toast.error("Failed to parse CSV file");
    },
  });

  // Import mutation
  const importMutation = useMutation({
    mutationFn: async () => {
      if (!selectedProjectId) throw new Error("No project selected");
      const response = await apiClient.post<ImportResult>("/imports/todoist", {
        project_id: selectedProjectId,
        csv_content: csvContent,
        section_mapping: sectionMapping,
      });
      return response.data;
    },
    onSuccess: (data) => {
      setImportResult(data);
      setStep("result");
      // Invalidate tasks query to refresh the project view
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      queryClient.invalidateQueries({ queryKey: ["project", selectedProjectId] });
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

  const handleNext = useCallback(() => {
    if (step === "upload" && parseResult && selectedProjectId) {
      setStep("configure");
    }
  }, [step, parseResult, selectedProjectId]);

  const handleImport = useCallback(() => {
    importMutation.mutate();
  }, [importMutation]);

  // Filter to only show projects where user has write or owner permission
  const activeProjects =
    projectsQuery.data?.filter((p) => {
      if (p.is_archived || p.is_template) return false;
      const userPermission = p.permissions?.find((perm) => perm.user_id === user?.id);
      return userPermission?.level === "owner" || userPermission?.level === "write";
    }) ?? [];
  const statuses = taskStatusesQuery.data ?? [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Import from Todoist</DialogTitle>
          <DialogDescription>
            {step === "upload" && "Upload your Todoist CSV export file or paste the content."}
            {step === "configure" && "Map Todoist sections to project statuses."}
            {step === "result" && "Import complete."}
          </DialogDescription>
        </DialogHeader>

        {step === "upload" && (
          <div className="space-y-4">
            {/* File Upload */}
            <div>
              <Label>Upload CSV file</Label>
              <div className="mt-2">
                <label className="border-muted hover:bg-accent flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed p-6 transition-colors">
                  <Upload className="text-muted-foreground mb-2 h-8 w-8" />
                  <span className="text-muted-foreground text-sm">
                    Click to upload or drag and drop
                  </span>
                  <input type="file" accept=".csv" className="hidden" onChange={handleFileUpload} />
                </label>
              </div>
            </div>

            {/* Or paste content */}
            <div className="text-muted-foreground text-center text-sm">or</div>

            <div>
              <Label htmlFor="csv-content">Paste CSV content</Label>
              <Textarea
                id="csv-content"
                placeholder="Paste your Todoist CSV export here..."
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

            {/* Parse result preview */}
            {parseResult && (
              <div className="bg-muted rounded-lg p-4">
                <div className="flex items-center gap-2">
                  <FileText className="h-4 w-4" />
                  <span className="font-medium">CSV parsed successfully</span>
                </div>
                <div className="text-muted-foreground mt-2 text-sm">
                  <p>Found {parseResult.task_count} tasks</p>
                  <p>Sections: {parseResult.sections.map((s) => s.name).join(", ") || "None"}</p>
                  {parseResult.has_subtasks && <p>Includes subtasks</p>}
                </div>
              </div>
            )}

            {/* Project selection */}
            {parseResult && (
              <div>
                <Label>Import to project</Label>
                <Select
                  value={selectedProjectId?.toString() ?? ""}
                  onValueChange={(value) => setSelectedProjectId(Number(value))}
                >
                  <SelectTrigger className="mt-2">
                    <SelectValue placeholder="Select a project" />
                  </SelectTrigger>
                  <SelectContent>
                    {activeProjects.map((project) => (
                      <SelectItem key={project.id} value={project.id.toString()}>
                        {project.icon && <span className="mr-2">{project.icon}</span>}
                        {project.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button onClick={handleNext} disabled={!parseResult || !selectedProjectId}>
                Next
              </Button>
            </div>
          </div>
        )}

        {step === "configure" && (
          <div className="space-y-4">
            <div>
              <Label>Map sections to statuses</Label>
              <p className="text-muted-foreground text-sm">
                Choose which project status each Todoist section should map to.
              </p>
            </div>

            <div className="space-y-3">
              {parseResult?.sections.map((section) => (
                <div key={section.name} className="flex items-center justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">{section.name}</p>
                    <p className="text-muted-foreground text-xs">
                      {section.task_count} task{section.task_count === 1 ? "" : "s"}
                    </p>
                  </div>
                  <Select
                    value={sectionMapping[section.name]?.toString() ?? ""}
                    onValueChange={(value) =>
                      setSectionMapping((prev) => ({
                        ...prev,
                        [section.name]: Number(value),
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
              <Button variant="outline" onClick={() => setStep("upload")}>
                Back
              </Button>
              <Button
                onClick={handleImport}
                disabled={
                  importMutation.isPending ||
                  Object.keys(sectionMapping).length !== parseResult?.sections.length
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
