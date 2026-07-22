import type { FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { TaskForm, type TaskFormProps } from "@/components/tasks/TaskForm";
import { Button } from "@/components/ui/button";
import {
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface ProjectTaskComposerProps {
  /** Controlled field set forwarded to the shared TaskForm (layout is fixed). */
  form: Omit<TaskFormProps, "layout">;
  canWrite: boolean;
  isArchived: boolean;
  isSubmitting: boolean;
  hasError: boolean;
  /** When true, a backdrop click won't close the dialog (unsaved input). */
  isDirty: boolean;
  onSubmit: () => void;
  onCancel?: () => void;
}

export const ProjectTaskComposer = ({
  form,
  canWrite,
  isArchived,
  isSubmitting,
  hasError,
  isDirty,
  onSubmit,
  onCancel,
}: ProjectTaskComposerProps) => {
  const { t } = useTranslation(["projects", "common"]);
  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onSubmit();
  };

  return (
    <DialogContent
      className="max-h-screen overflow-y-auto bg-card"
      // Only block a backdrop click while there's unsaved input, so a stray
      // click can't discard an in-progress task. When the form is untouched,
      // clicking outside closes it as usual. Escape and Cancel always close.
      onInteractOutside={(event) => {
        if (isDirty) event.preventDefault();
      }}
    >
      <DialogHeader>
        <DialogTitle>{t("taskComposer.title")}</DialogTitle>
        <DialogDescription>{t("taskComposer.description")}</DialogDescription>
      </DialogHeader>
      <div>
        {isArchived ? (
          <p className="text-muted-foreground text-sm">{t("taskComposer.archivedMessage")}</p>
        ) : canWrite ? (
          <form className="space-y-4" onSubmit={handleSubmit}>
            <TaskForm {...form} layout="dialog" />
            <div className="flex flex-wrap gap-2">
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting ? t("taskComposer.saving") : t("taskComposer.createTask")}
              </Button>
              {onCancel ? (
                <Button type="button" variant="outline" onClick={onCancel} disabled={isSubmitting}>
                  {t("common:cancel")}
                </Button>
              ) : null}
              {hasError ? (
                <p className="text-destructive text-sm">{t("taskComposer.createError")}</p>
              ) : null}
            </div>
          </form>
        ) : (
          <p className="text-muted-foreground text-sm">{t("taskComposer.noWriteAccess")}</p>
        )}
      </div>
    </DialogContent>
  );
};
