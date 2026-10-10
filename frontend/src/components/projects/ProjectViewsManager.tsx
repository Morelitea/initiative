import { Link } from "@tanstack/react-router";
import { ChevronDown, ChevronUp, Pencil, Star, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ToolViewSetRead, ToolViewWrite } from "@/api/generated/initiativeAPI.schemas";
import { viewLayouts, viewName } from "@/components/projects/projectTasksConfig";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { usePutProjectViews, viewSetWrite, viewWrites } from "@/hooks/useProjectViews";
import { atLeast, useWidthClass } from "@/hooks/useWidthClass";
import { specFromApi, taskFilterCount } from "@/lib/filters/taskFilters";
import { cn } from "@/lib/utils";

type ProjectViewsManagerProps = {
  projectId: number;
  /** Where the project's views are edited. */
  editHref?: string;
  /** The project's views, read by someone who may configure them. */
  set: ToolViewSetRead;
};

/**
 * The project's views: their names, their order, and which one it opens on.
 * Every change saves the whole set, and the list waits while one is saving.
 *
 * A view's layout, card and columns are laid out in the view editor, which
 * Edit views opens, and its filters where they are used: on the task list,
 * then "Save as view" or "Update <view>".
 */
export const ProjectViewsManager = ({ projectId, editHref, set }: ProjectViewsManagerProps) => {
  const { t } = useTranslation(["projects", "common"]);
  const wide = atLeast(useWidthClass(), "md");
  const put = usePutProjectViews(projectId);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  const writes = viewWrites(set);
  // Each save replaces the whole set, so one waits for the last: a second,
  // built from the same set, would undo it.
  const saving = put.isPending;
  const save = (views: ToolViewWrite[]) => {
    if (!saving) put.mutate(viewSetWrite(set, views));
  };

  const move = (index: number, delta: number) => {
    const target = index + delta;
    if (target < 0 || target >= writes.length) return;
    const ordered = [...writes];
    const [moved] = ordered.splice(index, 1);
    ordered.splice(target, 0, moved);
    save(ordered);
  };

  const remove = (slug: string) => {
    const rest = writes.filter((view) => view.slug !== slug);
    // The set always has a default; losing it passes it to the first.
    save(
      rest.some((view) => view.is_default)
        ? rest
        : rest.map((view, index) => ({ ...view, is_default: index === 0 }))
    );
  };

  const deleting = set.views.find((view) => view.slug === pendingDelete);

  return (
    <>
      <Card>
        <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-2">
          <div className="space-y-1.5">
            <CardTitle>{t("views.heading")}</CardTitle>
            <CardDescription>{t("views.description")}</CardDescription>
          </div>
          {/* The editor needs room beside its canvas. */}
          {editHref && wide ? (
            <Button asChild variant="outline" size="sm">
              <Link to={editHref}>
                <Pencil className="h-4 w-4" />
                {t("viewEditor.open")}
              </Link>
            </Button>
          ) : null}
        </CardHeader>
        <CardContent className="space-y-2">
          {set.views.map((view, index) => (
            <ViewRow
              key={view.slug}
              name={viewName(view, t)}
              layoutType={view.definition.layout.type}
              filterCount={taskFilterCount(specFromApi(view.definition.filters))}
              isDefault={view.is_default}
              isFirst={index === 0}
              isLast={index === set.views.length - 1}
              canDelete={set.views.length > 1}
              saving={saving}
              onMoveUp={() => move(index, -1)}
              onMoveDown={() => move(index, 1)}
              onRename={(name) =>
                save(writes.map((each, at) => (at === index ? { ...each, name } : each)))
              }
              onMakeDefault={() =>
                save(writes.map((each, at) => ({ ...each, is_default: at === index })))
              }
              onDelete={() => setPendingDelete(view.slug)}
            />
          ))}
        </CardContent>
      </Card>

      <ConfirmDialog
        open={deleting !== undefined}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
        title={t("views.delete")}
        description={t("views.deleteConfirm", { name: deleting ? viewName(deleting, t) : "" })}
        confirmLabel={t("common:delete")}
        destructive
        onConfirm={() => {
          if (deleting) remove(deleting.slug);
          setPendingDelete(null);
        }}
      />
    </>
  );
};

type ViewRowProps = {
  name: string;
  layoutType: keyof typeof viewLayouts;
  filterCount: number;
  isDefault: boolean;
  isFirst: boolean;
  isLast: boolean;
  canDelete: boolean;
  saving: boolean;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onRename: (name: string) => void;
  onMakeDefault: () => void;
  onDelete: () => void;
};

const ViewRow = ({
  name,
  layoutType,
  filterCount,
  isDefault,
  isFirst,
  isLast,
  canDelete,
  saving,
  onMoveUp,
  onMoveDown,
  onRename,
  onMakeDefault,
  onDelete,
}: ViewRowProps) => {
  const { t } = useTranslation(["projects", "common"]);
  const [draft, setDraft] = useState(name);
  useEffect(() => setDraft(name), [name]);
  const layout = viewLayouts[layoutType];
  const LayoutIcon = layout.icon;

  const commit = () => {
    const trimmed = draft.trim();
    if (!trimmed || trimmed === name) {
      setDraft(name);
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
          disabled={saving || isFirst}
          onClick={onMoveUp}
          aria-label={t("views.moveUp", { name })}
        >
          <ChevronUp className="h-4 w-4" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-5 w-6"
          disabled={saving || isLast}
          onClick={onMoveDown}
          aria-label={t("views.moveDown", { name })}
        >
          <ChevronDown className="h-4 w-4" />
        </Button>
      </div>
      <Input
        value={draft}
        aria-label={t("views.name")}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => event.key === "Enter" && event.currentTarget.blur()}
        maxLength={100}
        readOnly={saving}
        className="w-full sm:w-56"
      />
      <span className="flex min-w-0 flex-1 items-center gap-2 truncate text-muted-foreground text-sm">
        <LayoutIcon className="h-4 w-4 shrink-0" />
        {t(layout.labelKey as never)}
        {filterCount > 0 ? ` · ${t("common:toolbar.filters")} · ${filterCount}` : ""}
      </span>
      <Button
        type="button"
        variant={isDefault ? "secondary" : "ghost"}
        size="sm"
        disabled={saving || isDefault}
        onClick={onMakeDefault}
        className="gap-2"
      >
        <Star className={cn("h-4 w-4", isDefault && "fill-current")} />
        {t("views.default")}
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        disabled={saving || !canDelete}
        onClick={onDelete}
        aria-label={t("views.deleteNamed", { name })}
      >
        <Trash2 className="h-4 w-4" />
      </Button>
    </div>
  );
};
