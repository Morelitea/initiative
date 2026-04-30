import { ChangeEvent, FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useRouter } from "@tanstack/react-router";

import { useImportProjectApiV1ProjectsImportPost } from "@/api/generated/projects/projects";
import type {
  InitiativeRead,
  ProjectExportEnvelopeOutput,
} from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
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
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { useGuildPath } from "@/lib/guildUrl";

interface ProjectImportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  creatableInitiatives: InitiativeRead[];
  defaultInitiativeId: string | null;
  onImported?: () => void;
}

export const ProjectImportDialog = ({
  open,
  onOpenChange,
  creatableInitiatives,
  defaultInitiativeId,
  onImported,
}: ProjectImportDialogProps) => {
  const { t } = useTranslation(["projects", "common"]);
  const router = useRouter();
  const gp = useGuildPath();

  const [envelope, setEnvelope] = useState<ProjectExportEnvelopeOutput | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [initiativeId, setInitiativeId] = useState<string | null>(defaultInitiativeId);
  const [fileName, setFileName] = useState<string>("");

  const importMutation = useImportProjectApiV1ProjectsImportPost();

  useEffect(() => {
    if (open) {
      setInitiativeId(defaultInitiativeId);
    } else {
      setEnvelope(null);
      setParseError(null);
      setFileName("");
    }
  }, [open, defaultInitiativeId]);

  const handleFileChange = async (e: ChangeEvent<HTMLInputElement>) => {
    setParseError(null);
    setEnvelope(null);
    const file = e.target.files?.[0];
    if (!file) {
      setFileName("");
      return;
    }
    setFileName(file.name);
    try {
      const text = await file.text();
      const parsed = JSON.parse(text) as ProjectExportEnvelopeOutput;
      if (
        !parsed ||
        typeof parsed !== "object" ||
        !("schema_version" in parsed) ||
        !parsed.project
      ) {
        setParseError(t("import.parseError"));
        return;
      }
      setEnvelope(parsed);
    } catch {
      setParseError(t("import.parseError"));
    }
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!envelope || !initiativeId) {
      return;
    }
    try {
      const result = await importMutation.mutateAsync({
        data: {
          envelope,
          initiative_id: Number(initiativeId),
        },
      });
      if (result.assignee_unmatched_emails && result.assignee_unmatched_emails.length > 0) {
        toast.warning(
          t("import.warningUnmatchedAssignees", {
            count: result.assignee_unmatched_emails.length,
            emails: result.assignee_unmatched_emails.join(", "),
          })
        );
      } else {
        toast.success(t("import.success", { name: result.project_name }));
      }
      onOpenChange(false);
      onImported?.();
      router.navigate({ to: gp(`/projects/${result.project_id}`) });
    } catch (err) {
      toast.error(getErrorMessage(err, "projects:import.error"));
    }
  };

  const isSubmitting = importMutation.isPending;
  const canSubmit = !!envelope && !!initiativeId && !isSubmitting;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("import.title")}</DialogTitle>
          <DialogDescription>{t("import.description")}</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="project-import-file">{t("import.selectFile")}</Label>
            <input
              id="project-import-file"
              type="file"
              accept=".json,application/json"
              onChange={handleFileChange}
              className="block w-full text-sm"
            />
            {fileName && !parseError ? (
              <p className="text-muted-foreground text-xs">{fileName}</p>
            ) : null}
            {parseError ? <p className="text-destructive text-sm">{parseError}</p> : null}
          </div>

          {envelope ? (
            <div className="bg-muted space-y-1 rounded-md p-3 text-sm">
              <p>
                <strong>{t("import.previewProject")}:</strong> {envelope.project.name}
              </p>
              <p>
                <strong>{t("import.previewTaskCount")}:</strong> {envelope.tasks.length}
              </p>
              <p>
                <strong>{t("import.previewSchemaVersion")}:</strong> {envelope.schema_version}
              </p>
            </div>
          ) : null}

          <div className="space-y-2">
            <Label htmlFor="project-import-initiative">{t("import.targetInitiative")}</Label>
            <Select
              value={initiativeId ?? undefined}
              onValueChange={(value) => setInitiativeId(value)}
            >
              <SelectTrigger id="project-import-initiative">
                <SelectValue placeholder={t("import.selectInitiative")} />
              </SelectTrigger>
              <SelectContent>
                {creatableInitiatives.map((init) => (
                  <SelectItem key={init.id} value={String(init.id)}>
                    {init.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={isSubmitting}
            >
              {t("common:cancel")}
            </Button>
            <Button type="submit" disabled={!canSubmit}>
              {isSubmitting ? t("import.importing") : t("import.importButton")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};
