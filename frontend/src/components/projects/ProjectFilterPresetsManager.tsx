import { ChevronDown, ChevronUp, Star, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { FilterPresetRead, ProjectRead } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  useDeleteFilterPreset,
  useFilterPresets,
  useReorderFilterPresets,
  useUpdateFilterPreset,
} from "@/hooks/useFilterPresets";
import { useUpdateProject } from "@/hooks/useProjects";
import { specFromApi, type TASK_VIEW_MODES, taskFilterCount } from "@/lib/filters/taskFilters";
import { cn } from "@/lib/utils";

type ProjectFilterPresetsManagerProps = {
  project: ProjectRead;
  /** Whether this viewer may curate presets — server-computed, never derived. */
  canManage: boolean;
};

/**
 * The project's saved views: which one it opens on, in which task view, and
 * the presets themselves.
 *
 * Filter *values* are deliberately not editable here. They are edited where
 * they are used — set the filters on the task list, then "Update <preset>" —
 * so the filter panel exists once rather than being remounted in settings.
 */
export const ProjectFilterPresetsManager = ({
  project,
  canManage,
}: ProjectFilterPresetsManagerProps) => {
  const { t } = useTranslation(["projects", "common"]);
  const presetsQuery = useFilterPresets(project.id);
  const presets = presetsQuery.data?.items ?? [];

  const updatePreset = useUpdateFilterPreset(project.id);
  const deletePreset = useDeleteFilterPreset(project.id);
  const reorderPresets = useReorderFilterPresets(project.id);
  const updateProject = useUpdateProject(project.id);

  const [pendingDelete, setPendingDelete] = useState<FilterPresetRead | null>(null);

  const move = (index: number, delta: number) => {
    const target = index + delta;
    if (target < 0 || target >= presets.length) return;
    const ordered = [...presets];
    const [moved] = ordered.splice(index, 1);
    ordered.splice(target, 0, moved);
    reorderPresets.mutate({
      items: ordered.map((preset, position) => ({ id: preset.id, position })),
    });
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{t("projects:settings.defaultView")}</CardTitle>
          <CardDescription>{t("projects:settings.defaultViewHint")}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="w-full space-y-2 sm:w-64">
            <Label htmlFor="default-view">{t("projects:settings.defaultView")}</Label>
            <Select
              value={project.default_view_mode ?? "table"}
              disabled={!canManage || updateProject.isPending}
              onValueChange={(value) =>
                updateProject.mutate({
                  default_view_mode: value as (typeof TASK_VIEW_MODES)[number],
                })
              }
            >
              <SelectTrigger id="default-view">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="table">{t("projects:tasks.viewTable")}</SelectItem>
                <SelectItem value="kanban">{t("projects:tasks.viewKanban")}</SelectItem>
                <SelectItem value="calendar">{t("projects:tasks.viewCalendar")}</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("projects:settings.filterPresetsHeading")}</CardTitle>
          <CardDescription>{t("projects:settings.filterPresetsDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {presets.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t("projects:settings.noPresets")}</p>
          ) : null}
          {presets.map((preset, index) => (
            <PresetRow
              key={preset.id}
              preset={preset}
              canManage={canManage}
              isFirst={index === 0}
              isLast={index === presets.length - 1}
              onMoveUp={() => move(index, -1)}
              onMoveDown={() => move(index, 1)}
              onRename={(name) => updatePreset.mutate({ presetId: preset.id, data: { name } })}
              onMakeDefault={() =>
                updatePreset.mutate({ presetId: preset.id, data: { is_default: true } })
              }
              onDelete={() => setPendingDelete(preset)}
            />
          ))}
        </CardContent>
      </Card>

      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
        title={t("projects:settings.deletePreset")}
        description={t("projects:settings.deletePresetConfirm", {
          name: pendingDelete?.name ?? "",
        })}
        confirmLabel={t("common:delete")}
        destructive
        onConfirm={() => {
          if (pendingDelete) deletePreset.mutate(pendingDelete.id);
          setPendingDelete(null);
        }}
      />
    </div>
  );
};

type PresetRowProps = {
  preset: FilterPresetRead;
  canManage: boolean;
  isFirst: boolean;
  isLast: boolean;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onRename: (name: string) => void;
  onMakeDefault: () => void;
  onDelete: () => void;
};

const PresetRow = ({
  preset,
  canManage,
  isFirst,
  isLast,
  onMoveUp,
  onMoveDown,
  onRename,
  onMakeDefault,
  onDelete,
}: PresetRowProps) => {
  const { t } = useTranslation(["projects", "common"]);
  const [name, setName] = useState(preset.name);
  useEffect(() => setName(preset.name), [preset.name]);

  const count = taskFilterCount(specFromApi(preset.filters));

  const commit = () => {
    const trimmed = name.trim();
    if (!trimmed || trimmed === preset.name) {
      setName(preset.name);
      return;
    }
    onRename(trimmed);
  };

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border p-2">
      {/* Arrows, not a grip: these move a row on click. A drag handle would
          promise dragging, which this list does not offer. */}
      <div className="flex shrink-0 flex-col">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-5 w-6"
          disabled={!canManage || isFirst}
          onClick={onMoveUp}
          aria-label={t("projects:settings.presetMoveUp")}
        >
          <ChevronUp className="h-4 w-4" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-5 w-6"
          disabled={!canManage || isLast}
          onClick={onMoveDown}
          aria-label={t("projects:settings.presetMoveDown")}
        >
          <ChevronDown className="h-4 w-4" />
        </Button>
      </div>
      <Input
        value={name}
        disabled={!canManage}
        onChange={(event) => setName(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => event.key === "Enter" && event.currentTarget.blur()}
        maxLength={100}
        className="w-full sm:w-56"
      />
      <span className="min-w-0 flex-1 truncate text-muted-foreground text-sm">
        {count === 0
          ? t("projects:settings.presetNoFilters")
          : t("projects:filters.heading") + ` · ${count}`}
      </span>
      <Button
        type="button"
        variant={preset.is_default ? "secondary" : "ghost"}
        size="sm"
        disabled={!canManage || preset.is_default}
        onClick={onMakeDefault}
        className="gap-2"
      >
        <Star className={cn("h-4 w-4", preset.is_default && "fill-current")} />
        {t("projects:settings.presetDefaultColumn")}
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        disabled={!canManage}
        onClick={onDelete}
        aria-label={t("projects:settings.deletePreset")}
      >
        <Trash2 className="h-4 w-4" />
      </Button>
    </div>
  );
};
