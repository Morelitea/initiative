import { useRouter } from "@tanstack/react-router";
import { type ChangeEvent, type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { useImportEnvelopeApiV1GGuildIdImportsEnvelopePost } from "@/api/generated/imports/imports";
import type { InitiativeRead } from "@/api/generated/initiativeAPI.schemas";
import { invalidateAllProjects } from "@/api/query-keys";
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
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { useGuildPath } from "@/lib/guildUrl";

/** The subset of the export envelope the preview reads. The file is
 * user-supplied input, so a narrow structural type is more honest than the
 * full schema — the backend re-validates the whole envelope on import. */
type ProjectExportEnvelope = {
  schema_version: number;
  project: { name: string };
  tasks: unknown[];
};

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
  const guildId = useActiveGuildId();

  const [envelope, setEnvelope] = useState<ProjectExportEnvelope | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [initiativeId, setInitiativeId] = useState<string | null>(defaultInitiativeId);
  const [fileName, setFileName] = useState<string>("");

  const importMutation = useImportEnvelopeApiV1GGuildIdImportsEnvelopePost();

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
    // Guard against pathological / crafted files that would otherwise
    // stall the tab during file.text() or JSON.parse. 50 MB is far
    // larger than a real project export and small enough to abort fast.
    const MAX_BYTES = 50 * 1024 * 1024;
    if (file.size > MAX_BYTES) {
      setFileName(file.name);
      setParseError(t("import.fileTooLarge"));
      return;
    }
    setFileName(file.name);
    try {
      const text = await file.text();
      const parsed = JSON.parse(text) as ProjectExportEnvelope;
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
      // The engine endpoint is a 201-inline / 202-job union; the generated
      // client returns data only, so discriminate by shape.
      const response = (await importMutation.mutateAsync({
        guildId,
        data: {
          // Backend types `envelope` as a free-form dict to keep the
          // export schema from being split into Input/Output by Pydantic;
          // we still serialize the strongly-typed parsed envelope.
          envelope: envelope as unknown as Record<string, unknown>,
          initiative_id: Number(initiativeId),
        },
      })) as
        | {
            result: {
              entity_id: number | null;
              entity_title: string;
              unmatched_emails: string[];
            };
          }
        | { id: number; status: string };
      void invalidateAllProjects();
      if ("result" in response) {
        const { result } = response;
        toast.success(t("import.success", { name: result.entity_title }));
        if (result.unmatched_emails.length > 0) {
          toast.warning(
            t("import.warningUnmatchedAssignees", {
              count: result.unmatched_emails.length,
              emails: result.unmatched_emails.join(", "),
            })
          );
        }
        onOpenChange(false);
        onImported?.();
        if (result.entity_id != null) {
          router.navigate({ to: gp(`/projects/${result.entity_id}`) });
        }
      } else {
        // A very large project queued as a background job — the inbox
        // notification delivers the outcome.
        toast.success(t("import.queued"));
        onOpenChange(false);
        onImported?.();
      }
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
            <div className="space-y-1 rounded-md bg-muted p-3 text-sm">
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
