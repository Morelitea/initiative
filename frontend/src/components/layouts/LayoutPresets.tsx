import { ArrowDown, ArrowUp, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { SortField } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ProjectTasksFilters } from "@/components/projects/ProjectTasksFilters";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  EMPTY_TASK_FILTERS,
  type TaskFilterSpec,
  tableSortFields,
  taskTableSorting,
} from "@/lib/filters/taskFilters";
import type { ListLayout } from "@/lib/layouts/draft";
import { type FieldDef, LAYOUT_NAMESPACES } from "@/lib/layouts/fields";
import {
  MAX_PRESETS,
  type Preset,
  presetName,
  presetSlug,
  presetsOf,
  storedPreset,
} from "@/lib/layouts/presets";
import type { TranslateFn } from "@/types/i18n";

import type { LayoutEdits } from "./LayoutEditor";
import type { LayoutProject } from "./LayoutSettingsPanel";

/** What a preset can sort a table by, as the task list names it, and the
 *  field (or key) that names it for a reader. */
const SORTS: readonly { field: string; label: { field: string } | { key: string } }[] = [
  { field: "title", label: { field: "title" } },
  { field: "due_date", label: { field: "dueDate" } },
  { field: "start_date", label: { field: "startDate" } },
  { field: "priority", label: { field: "priority" } },
  { field: "status_position", label: { key: "tasks:columns.status" } },
  { field: "tag_name", label: { field: "tags" } },
];

/** Picked in the sort select for "no sort of its own". */
const NO_SORT = "none";

/**
 * The presets a project's list offers: each one's name, and buttons to change,
 * move or remove it, then one to add another. They are kept with the layout,
 * and saved with it.
 */
export const LayoutPresets = ({
  layout,
  project,
  fields,
  edits,
}: {
  layout: ListLayout;
  project: LayoutProject;
  fields: ReadonlyMap<string, FieldDef>;
  edits: LayoutEdits;
}) => {
  const { t } = useTranslation(LAYOUT_NAMESPACES);
  const translate = t as TranslateFn;
  const presets = presetsOf(layout.definition);
  // The preset open in the dialog, by its place; null adds one.
  const [open, setOpen] = useState<{ index: number | null } | null>(null);

  const change = (next: Preset[]) => edits.changePresets(next.map(storedPreset));
  const move = (index: number, by: number) => {
    const next = [...presets];
    const [moved] = next.splice(index, 1);
    next.splice(index + by, 0, moved);
    change(next);
  };

  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <h3 className="font-medium text-sm">{translate("layoutEditor.presets.heading")}</h3>
        <p className="text-muted-foreground text-xs">{translate("layoutEditor.presets.help")}</p>
      </div>
      {presets.length === 0 ? (
        <p className="text-muted-foreground text-sm">{translate("layoutEditor.presets.none")}</p>
      ) : (
        <ul className="space-y-1">
          {presets.map((preset, index) => {
            const name = presetName(preset, translate);
            return (
              <li key={preset.slug} className="flex items-center gap-1">
                <span className="min-w-0 flex-1 truncate text-sm">{name}</span>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  aria-label={translate("layoutEditor.presets.edit", { name })}
                  onClick={() => setOpen({ index })}
                >
                  <Pencil className="h-3.5 w-3.5" />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  aria-label={translate("layoutEditor.presets.moveUp", { name })}
                  disabled={index === 0}
                  onClick={() => move(index, -1)}
                >
                  <ArrowUp className="h-3.5 w-3.5" />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  aria-label={translate("layoutEditor.presets.moveDown", { name })}
                  disabled={index === presets.length - 1}
                  onClick={() => move(index, 1)}
                >
                  <ArrowDown className="h-3.5 w-3.5" />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  aria-label={translate("layoutEditor.presets.remove", { name })}
                  onClick={() => change(presets.filter((_, each) => each !== index))}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </li>
            );
          })}
        </ul>
      )}
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={presets.length >= MAX_PRESETS}
        onClick={() => setOpen({ index: null })}
      >
        <Plus className="h-4 w-4" />
        {translate("layoutEditor.presets.add")}
      </Button>
      {presets.length >= MAX_PRESETS ? (
        <p className="text-muted-foreground text-xs">
          {translate("layoutEditor.presets.full", { count: MAX_PRESETS })}
        </p>
      ) : null}
      {open ? (
        <PresetDialog
          preset={open.index === null ? null : presets[open.index]}
          sortable={layout.kind === "table"}
          project={project}
          fields={fields}
          onClose={() => setOpen(null)}
          onSubmit={(name, spec, sorting) => {
            const next = [...presets];
            if (open.index === null) {
              const slug = presetSlug(
                name,
                presets.map((each) => each.slug)
              );
              next.push({ slug, name, spec, sorting });
            } else {
              // A rename keeps the slug, so links to it still open it. A shipped
              // one keeps being named in each reader's words until renamed.
              const was = next[open.index];
              const renamed = name !== presetName(was, translate);
              next[open.index] = {
                ...was,
                name,
                nameKey: renamed ? undefined : was.nameKey,
                spec,
                sorting,
              };
            }
            change(next);
            setOpen(null);
          }}
        />
      ) : null}
    </div>
  );
};

/** A preset's name, filters and, on a table, sort, changed together. */
const PresetDialog = ({
  preset,
  sortable,
  project,
  fields,
  onClose,
  onSubmit,
}: {
  /** The preset changed, or null for a new one. */
  preset: Preset | null;
  /** The list is a table, which a preset can sort. */
  sortable: boolean;
  project: LayoutProject;
  fields: ReadonlyMap<string, FieldDef>;
  onClose: () => void;
  onSubmit: (name: string, spec: TaskFilterSpec, sorting: Preset["sorting"]) => void;
}) => {
  const { t } = useTranslation([...LAYOUT_NAMESPACES, "common"]);
  const translate = t as TranslateFn;
  const [name, setName] = useState(preset ? presetName(preset, translate) : "");
  const [spec, setSpec] = useState(preset?.spec ?? EMPTY_TASK_FILTERS);
  const [sort, setSort] = useState<SortField | null>(
    tableSortFields(preset?.sorting ?? [])[0] ?? null
  );
  const trimmed = name.trim();
  const sortLabel = (label: (typeof SORTS)[number]["label"]) =>
    "key" in label
      ? translate(label.key)
      : translate(fields.get(label.field)?.label ?? label.field);

  return (
    <Dialog open onOpenChange={(next) => (next ? undefined : onClose())}>
      <DialogContent className="max-w-2xl">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (!trimmed) return;
            onSubmit(trimmed, spec, sort ? taskTableSorting([sort]) : []);
          }}
          className="space-y-4"
        >
          <DialogHeader>
            <DialogTitle>
              {translate(
                preset ? "layoutEditor.presets.editTitle" : "layoutEditor.presets.addTitle"
              )}
            </DialogTitle>
            <DialogDescription>{translate("layoutEditor.presets.dialogHelp")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="preset-name">{translate("layoutEditor.presets.name")}</Label>
            <Input
              id="preset-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              maxLength={100}
              autoFocus
            />
          </div>
          <ProjectTasksFilters
            memberScope={{ type: "canOpen", tool: Tool.project, id: project.id }}
            taskStatuses={project.statuses}
            initiativeId={project.initiativeId}
            value={spec}
            onChange={setSpec}
          />
          {sortable ? (
            <div className="grid-cols-pair grid gap-4">
              <div className="space-y-2">
                <Label htmlFor="preset-sort">{translate("layoutEditor.presets.sortBy")}</Label>
                <Select
                  value={sort?.field ?? NO_SORT}
                  onValueChange={(field) =>
                    setSort(field === NO_SORT ? null : { field, dir: sort?.dir ?? "asc" })
                  }
                >
                  <SelectTrigger id="preset-sort">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NO_SORT}>
                      {translate("layoutEditor.presets.noSort")}
                    </SelectItem>
                    {SORTS.map(({ field, label }) => (
                      <SelectItem key={field} value={field}>
                        {sortLabel(label)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex items-center gap-2 self-end pb-2">
                <Switch
                  id="preset-descending"
                  checked={sort?.dir === "desc"}
                  disabled={!sort}
                  onCheckedChange={(checked) =>
                    sort && setSort({ ...sort, dir: checked ? "desc" : "asc" })
                  }
                />
                <Label htmlFor="preset-descending">
                  {translate("layoutEditor.presets.descending")}
                </Label>
              </div>
            </div>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {translate("common:cancel")}
            </Button>
            <Button type="submit" disabled={!trimmed}>
              {translate("common:done")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};
