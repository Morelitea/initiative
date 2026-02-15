import { useState, useCallback, useEffect } from "react";
import { useTranslation } from "react-i18next";
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
  const { t } = useTranslation("import");
  const { user } = useAuth();
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
        toast.error(t("vikunja.noProjectsFound"));
      } else {
        setStep("select-project");
      }
    },
    onError: () => {
      toast.error(t("vikunja.parseFailed"));
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
          <DialogTitle>{t("vikunja.title")}</DialogTitle>
          <DialogDescription>
            {step === "upload" && t("vikunja.stepUploadDescription")}
            {step === "select-project" && t("vikunja.stepSelectProjectDescription")}
            {step === "configure" && t("vikunja.stepConfigureDescription")}
            {step === "result" && t("common.resultTitle")}
          </DialogDescription>
        </DialogHeader>

        {step === "upload" && (
          <div className="space-y-4">
            <div>
              <Label>{t("vikunja.uploadFileLabel")}</Label>
              <div className="mt-2">
                <label className="border-muted hover:bg-accent flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed p-6 transition-colors">
                  <Upload className="text-muted-foreground mb-2 h-8 w-8" />
                  <span className="text-muted-foreground text-sm">
                    {t("common.uploadDragDrop")}
                  </span>
                  <span className="text-muted-foreground mt-1 text-xs">
                    {t("vikunja.uploadHint")}
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

            <div className="text-muted-foreground text-center text-sm">{t("common.or")}</div>

            <div>
              <Label htmlFor="json-content">{t("vikunja.pasteLabel")}</Label>
              <Textarea
                id="json-content"
                placeholder={t("vikunja.jsonPlaceholder")}
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

        {step === "select-project" && parseResult && (
          <div className="space-y-4">
            <div className="bg-muted rounded-lg p-4">
              <div className="flex items-center gap-2">
                <FileText className="h-4 w-4" />
                <span className="font-medium">{t("vikunja.exportParsed")}</span>
              </div>
              <p className="text-muted-foreground mt-1 text-sm">
                {t("vikunja.totalTasks", {
                  projectCount: parseResult.projects.length,
                  projectLabel: t("vikunja.projectsDetected", {
                    count: parseResult.projects.length,
                  })
                    .split(" ")
                    .slice(1)
                    .join(" "),
                  taskCount: parseResult.total_tasks,
                })}
              </p>
            </div>

            <div>
              <Label>{t("vikunja.importFromProject")}</Label>
              <Select
                value={selectedSourceProjectId?.toString() ?? ""}
                onValueChange={(value) => setSelectedSourceProjectId(Number(value))}
              >
                <SelectTrigger className="mt-2">
                  <SelectValue placeholder={t("vikunja.selectSourceProjectPlaceholder")} />
                </SelectTrigger>
                <SelectContent className="max-h-60">
                  {parseResult.projects.map((project) => (
                    <SelectItem key={project.id} value={project.id.toString()}>
                      {project.name} ({t("vikunja.tasksCount", { count: project.task_count })})
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
                onClick={handleSelectSourceProject}
                disabled={!selectedSourceProjectId || !selectedTargetProjectId}
              >
                {t("common.next")}
              </Button>
            </div>
          </div>
        )}

        {step === "configure" && selectedSourceProject && (
          <div className="space-y-4">
            <div>
              <Label>{t("vikunja.mapBucketsLabel")}</Label>
              <p className="text-muted-foreground text-sm">{t("vikunja.mapBucketsDescription")}</p>
            </div>

            <div className="space-y-3">
              {selectedSourceProject.buckets.map((bucket) => (
                <div key={bucket.id} className="flex items-center justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">{bucket.name}</p>
                    <p className="text-muted-foreground text-xs">
                      {t("vikunja.taskCount", { count: bucket.task_count })}
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
              <Button variant="outline" onClick={() => setStep("select-project")}>
                {t("common.back")}
              </Button>
              <Button
                onClick={handleImport}
                disabled={
                  importMutation.isPending ||
                  Object.keys(bucketMapping).length !== selectedSourceProject.buckets.length
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
