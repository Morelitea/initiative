import { type ReactNode, useEffect, useMemo, useState } from "react";
import { AlertTriangle } from "lucide-react";

import type { Project } from "@/types/api";
import { SearchableCombobox } from "@/components/ui/searchable-combobox";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

type MoveTaskDialogProps = {
  trigger?: ReactNode;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projects: Project[];
  currentProjectId?: number | null;
  isLoading?: boolean;
  isSaving?: boolean;
  hasError?: boolean;
  onConfirm: (targetProjectId: number) => void;
};

export const MoveTaskDialog = ({
  trigger,
  open,
  onOpenChange,
  projects,
  currentProjectId = null,
  isLoading = false,
  isSaving = false,
  hasError = false,
  onConfirm,
}: MoveTaskDialogProps) => {
  const availableProjects = useMemo(() => {
    return projects.filter((project) => project.id !== currentProjectId);
  }, [projects, currentProjectId]);
  const [selectedValue, setSelectedValue] = useState<string>("");

  useEffect(() => {
    if (!open) {
      setSelectedValue("");
      return;
    }
    if (selectedValue) {
      const stillValid = availableProjects.some((project) => String(project.id) === selectedValue);
      if (stillValid) {
        return;
      }
    }
    const fallback = availableProjects[0];
    setSelectedValue(fallback ? String(fallback.id) : "");
  }, [open, availableProjects, selectedValue]);

  const isDisabled = isLoading || availableProjects.length === 0 || hasError;
  const confirmDisabled = isDisabled || isSaving || !selectedValue;

  const handleConfirm = () => {
    const parsed = Number(selectedValue);
    if (!Number.isFinite(parsed)) {
      return;
    }
    onConfirm(parsed);
  };

  const comboboxItems = useMemo(
    () =>
      availableProjects.map((project) => ({
        value: String(project.id),
        label: project.icon ? `${project.icon} ${project.name}` : project.name,
      })),
    [availableProjects]
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {trigger ? <DialogTrigger asChild>{trigger}</DialogTrigger> : null}
      <DialogContent className="bg-card">
        <DialogHeader>
          <DialogTitle>Move task to another project</DialogTitle>
          <DialogDescription>
            Select a destination project within the current guild. You can only move tasks to
            projects where you have permission to create new work.
          </DialogDescription>
        </DialogHeader>

        {hasError ? (
          <p className="text-destructive text-sm">Unable to load writable projects.</p>
        ) : isLoading ? (
          <p className="text-muted-foreground text-sm">Loading available projects…</p>
        ) : availableProjects.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            You don&rsquo;t have any other writable projects available yet.
          </p>
        ) : (
          <SearchableCombobox
            items={comboboxItems}
            value={selectedValue}
            onValueChange={setSelectedValue}
            placeholder="Search projects…"
            disabled={isDisabled}
          />
        )}

        <div className="flex items-start gap-2 rounded-md border px-3 py-2 text-sm">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>Moving this task will reset its status to &lsquo;Backlog&rsquo;.</span>
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={isSaving}
          >
            Cancel
          </Button>
          <Button type="button" onClick={handleConfirm} disabled={confirmDisabled}>
            {isSaving ? "Moving…" : "Move task"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
