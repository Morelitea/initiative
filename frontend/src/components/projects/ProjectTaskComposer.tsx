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
  onSubmit: () => void;
  onCancel?: () => void;
}

export const ProjectTaskComposer = ({
  form,
  canWrite,
  isArchived,
  isSubmitting,
  hasError,
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
      // Don't let an accidental backdrop click discard an in-progress task.
      // Escape and the explicit Cancel button still close the dialog.
      onInteractOutside={(event) => event.preventDefault()}
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
