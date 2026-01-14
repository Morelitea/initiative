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

interface VikunjaBucket {
  id: number;
  name: string;
  task_count: number;
}

interface VikunjaProject {
  id: number;
  name: string;
  task_count: number;
  buckets: VikunjaBucket[];
}

interface VikunjaParseResult {
  projects: VikunjaProject[];
  total_tasks: number;
}

interface ImportResult {
  tasks_created: number;
  subtasks_created: number;
  tasks_failed: number;
  errors: string[];
}

interface VikunjaImportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type Step = "upload" | "select-project" | "configure" | "result";

// Suggest a status based on bucket name
const suggestStatusForBucket = (
  bucketName: string,
  statuses: ProjectTaskStatus[]
): number | undefined => {
  const lowerName = bucketName.toLowerCase();

  const categoryMapping: Record<string, string[]> = {
    backlog: ["backlog", "inbox", "later", "someday", "no bucket"],
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

export const VikunjaImportDialog = ({ open, onOpenChange }: VikunjaImportDialogProps) => {
  const [step, setStep] = useState<Step>("upload");
  const [jsonContent, setJsonContent] = useState("");
  const [parseResult, setParseResult] = useState<VikunjaParseResult | null>(null);
  const [selectedSourceProjectId, setSelectedSourceProjectId] = useState<number | null>(null);
  const [selectedTargetProjectId, setSelectedTargetProjectId] = useState<number | null>(null);
  const [bucketMapping, setBucketMapping] = useState<Record<number, number>>({});
  const [importResult, setImportResult] = useState<ImportResult | null>(null);

  // Reset state when dialog closes
  useEffect(() => {
    if (!open) {
      setStep("upload");
      setJsonContent("");
      setParseResult(null);
      setSelectedSourceProjectId(null);
      setSelectedTargetProjectId(null);
      setBucketMapping({});
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

  // Get selected source project
  const selectedSourceProject = parseResult?.projects.find((p) => p.id === selectedSourceProjectId);

  // Initialize bucket mapping when statuses load
  useEffect(() => {
    if (selectedSourceProject && taskStatusesQuery.data) {
      const newMapping: Record<number, number> = {};
      for (const bucket of selectedSourceProject.buckets) {
        const suggestedId = suggestStatusForBucket(bucket.name, taskStatusesQuery.data);
        if (suggestedId !== undefined) {
          newMapping[bucket.id] = suggestedId;
        }
      }
      setBucketMapping(newMapping);
    }
  }, [selectedSourceProject, taskStatusesQuery.data]);

  // Parse JSON mutation
  const parseMutation = useMutation({
    mutationFn: async (content: string) => {
      const response = await apiClient.post<VikunjaParseResult>("/imports/vikunja/parse", content, {
        headers: { "Content-Type": "text/plain" },
      });
      return response.data;
    },
    onSuccess: (data) => {
      setParseResult(data);
      if (data.projects.length === 0) {
        toast.error("No projects with tasks found in the export");
      } else {
        setStep("select-project");
      }
    },
    onError: () => {
      toast.error("Failed to parse JSON file");
    },
  });

  // Import mutation
  const importMutation = useMutation({
    mutationFn: async () => {
      if (!selectedTargetProjectId) throw new Error("No target project selected");
      if (!selectedSourceProjectId) throw new Error("No source project selected");
      const response = await apiClient.post<ImportResult>("/imports/vikunja", {
        project_id: selectedTargetProjectId,
        json_content: jsonContent,
        source_project_id: selectedSourceProjectId,
        bucket_mapping: bucketMapping,
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
        setJsonContent(content);
        parseMutation.mutate(content);
      };
      reader.readAsText(file);
    },
    [parseMutation]
  );

  const handlePasteContent = useCallback(() => {
    if (jsonContent.trim()) {
      parseMutation.mutate(jsonContent);
    }
  }, [jsonContent, parseMutation]);

  const handleSelectSourceProject = useCallback(() => {
    if (selectedSourceProjectId && selectedTargetProjectId) {
      setStep("configure");
    }
  }, [selectedSourceProjectId, selectedTargetProjectId]);

  const handleImport = useCallback(() => {
    importMutation.mutate();
  }, [importMutation]);

  const activeProjects = projectsQuery.data?.filter((p) => !p.is_archived && !p.is_template) ?? [];
  const statuses = taskStatusesQuery.data ?? [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Import from Vikunja</DialogTitle>
          <DialogDescription>
            {step === "upload" &&
              "Upload the data.json file from your Vikunja backup (unzip the backup first)."}
            {step === "select-project" &&
              "Select which project to import from and where to import to."}
            {step === "configure" && "Map Vikunja buckets to project statuses."}
            {step === "result" && "Import complete."}
          </DialogDescription>
        </DialogHeader>

        {step === "upload" && (
          <div className="space-y-4">
            <div>
              <Label>Upload data.json</Label>
              <div className="mt-2">
                <label className="border-muted hover:bg-accent flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed p-6 transition-colors">
                  <Upload className="text-muted-foreground mb-2 h-8 w-8" />
                  <span className="text-muted-foreground text-sm">
                    Click to upload or drag and drop
                  </span>
                  <span className="text-muted-foreground mt-1 text-xs">
                    Found in your unzipped Vikunja backup
                  </span>
                  <input
                    type="file"
                    accept=".json"
                    className="hidden"
                    onChange={handleFileUpload}
                  />
                </label>
              </div>
            </div>

            <div className="text-muted-foreground text-center text-sm">or</div>

            <div>
              <Label htmlFor="json-content">Paste JSON content</Label>
              <Textarea
                id="json-content"
                placeholder="Paste your Vikunja JSON export here..."
                value={jsonContent}
                onChange={(e) => setJsonContent(e.target.value)}
                className="mt-2 h-32 font-mono text-xs"
              />
              <Button
                variant="outline"
                size="sm"
                className="mt-2"
                onClick={handlePasteContent}
                disabled={!jsonContent.trim() || parseMutation.isPending}
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

        {step === "select-project" && parseResult && (
          <div className="space-y-4">
            <div className="bg-muted rounded-lg p-4">
              <div className="flex items-center gap-2">
                <FileText className="h-4 w-4" />
                <span className="font-medium">Export parsed successfully</span>
              </div>
              <p className="text-muted-foreground mt-1 text-sm">
                Found {parseResult.projects.length} project
                {parseResult.projects.length === 1 ? "" : "s"} with {parseResult.total_tasks} total
                tasks
              </p>
            </div>

            <div>
              <Label>Import from Vikunja project</Label>
              <Select
                value={selectedSourceProjectId?.toString() ?? ""}
                onValueChange={(value) => setSelectedSourceProjectId(Number(value))}
              >
                <SelectTrigger className="mt-2">
                  <SelectValue placeholder="Select a Vikunja project" />
                </SelectTrigger>
                <SelectContent className="max-h-60">
                  {parseResult.projects.map((project) => (
                    <SelectItem key={project.id} value={project.id.toString()}>
                      {project.name} ({project.task_count} tasks)
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
                onClick={handleSelectSourceProject}
                disabled={!selectedSourceProjectId || !selectedTargetProjectId}
              >
                Next
              </Button>
            </div>
          </div>
        )}

        {step === "configure" && selectedSourceProject && (
          <div className="space-y-4">
            <div>
              <Label>Map buckets to statuses</Label>
              <p className="text-muted-foreground text-sm">
                Choose which project status each Vikunja bucket should map to.
              </p>
            </div>

            <div className="space-y-3">
              {selectedSourceProject.buckets.map((bucket) => (
                <div key={bucket.id} className="flex items-center justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">{bucket.name}</p>
                    <p className="text-muted-foreground text-xs">
                      {bucket.task_count} task{bucket.task_count === 1 ? "" : "s"}
                    </p>
                  </div>
                  <Select
                    value={bucketMapping[bucket.id]?.toString() ?? ""}
                    onValueChange={(value) =>
                      setBucketMapping((prev) => ({
                        ...prev,
                        [bucket.id]: Number(value),
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
              <Button variant="outline" onClick={() => setStep("select-project")}>
                Back
              </Button>
              <Button
                onClick={handleImport}
                disabled={
                  importMutation.isPending ||
                  Object.keys(bucketMapping).length !== selectedSourceProject.buckets.length
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
