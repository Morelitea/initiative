import { useBlocker } from "@tanstack/react-router";
import { Laptop, Redo2, Smartphone, Tablet, Undo2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  TaskStatusRead,
  ToolViewSetRead,
  ToolViewWrite,
  ViewDefinitionInput,
} from "@/api/generated/initiativeAPI.schemas";
import { viewName } from "@/components/projects/projectTasksConfig";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { usePutProjectViews, viewSetWrite, viewWrites } from "@/hooks/useProjectViews";
import { useProperties } from "@/hooks/useProperties";
import { toast } from "@/lib/mascotToast";
import { historyReducer, startHistory } from "@/lib/views/draft";
import { pluginFields, usePluginsOnItems } from "@/lib/views/plugins";
import { taskFields } from "@/lib/views/tasks";

import { type PreviewWidth, ViewCanvas } from "./ViewCanvas";
import { ViewOutline } from "./ViewOutline";
import { ViewSettingsPanel } from "./ViewSettingsPanel";

const WIDTHS: { width: PreviewWidth; icon: typeof Laptop }[] = [
  { width: "desktop", icon: Laptop },
  { width: "tablet", icon: Tablet },
  { width: "phone", icon: Smartphone },
];

/**
 * A project's views, edited where they are seen. It takes the whole screen:
 * the views and what can be done to them across the top, the outline of the
 * one open on the left, that view drawn with the project's tasks in the
 * middle, and the settings of what is selected on the right.
 *
 * Every change is a draft until Save, which stores the whole set; readers see
 * the saved views until then. Undo and redo cover every change since the
 * editor opened, and leaving with changes asks first.
 */
export const ViewEditor = ({
  projectId,
  initiativeId,
  statuses,
  set,
  initialSlug,
  onClose,
}: {
  projectId: number;
  initiativeId: number;
  statuses: TaskStatusRead[];
  /** The project's views, read by someone who may configure them. */
  set: ToolViewSetRead;
  initialSlug?: string;
  onClose: () => void;
}) => {
  const { t, i18n } = useTranslation(["projects", "common"]);
  const saved = useMemo(() => viewWrites(set), [set]);
  const [history, dispatch] = useReducer(historyReducer, saved, startHistory);
  const views = history.present;
  const [active, setActive] = useState(() =>
    Math.max(
      0,
      saved.findIndex((view) => (initialSlug ? view.slug === initialSlug : view.is_default))
    )
  );
  const current = views[Math.min(active, views.length - 1)];
  const [selected, setSelected] = useState("view");
  const [width, setWidth] = useState<PreviewWidth>("desktop");
  const dirty = JSON.stringify(views) !== JSON.stringify(saved);

  const { data: definitions = [] } = useProperties({ initiativeId });
  const plugins = usePluginsOnItems(initiativeId);
  const fields = useMemo(
    () => taskFields(definitions, pluginFields(plugins, i18n.language)),
    [definitions, plugins, i18n.language]
  );

  const change = useCallback(
    (next: (view: ToolViewWrite) => ToolViewWrite) =>
      dispatch({
        type: "change",
        views: views.map((view, index) => (index === active ? next(view) : view)),
      }),
    [views, active]
  );
  const changeDefinition = (definition: ViewDefinitionInput) =>
    change((view) => ({ ...view, definition }));

  const put = usePutProjectViews(projectId);
  const save = () =>
    put.mutate(viewSetWrite(set, views), {
      onSuccess: (stored) => {
        dispatch({ type: "reset", views: viewWrites(stored) });
        toast.success(t("viewEditor.saved"));
      },
    });

  // Leaving on purpose (Close after the question, or after a save) passes.
  const leaving = useRef(false);
  const blocker = useBlocker({
    shouldBlockFn: () => dirty && !leaving.current,
    enableBeforeUnload: () => dirty && !leaving.current,
    withResolver: true,
  });
  const [asking, setAsking] = useState(false);
  const close = () => {
    if (dirty) setAsking(true);
    else onClose();
  };

  // The keys people already reach for: undo and redo, wherever focus is but
  // a text field, which keeps its own.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, [contenteditable='true']")) return;
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== "z") return;
      event.preventDefault();
      dispatch({ type: event.shiftKey ? "redo" : "undo" });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col bg-background"
      role="dialog"
      aria-modal="true"
      aria-label={t("viewEditor.title")}
    >
      <header className="flex h-14 shrink-0 items-center gap-2 border-b px-3">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={t("viewEditor.close")}
          onClick={close}
        >
          <X className="h-4 w-4" />
        </Button>
        <Select
          value={String(active)}
          onValueChange={(value) => {
            setActive(Number(value));
            setSelected("view");
          }}
        >
          <SelectTrigger className="w-56" aria-label={t("viewEditor.view")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {views.map((view, index) => (
              <SelectItem key={view.slug ?? index} value={String(index)}>
                {viewName({ slug: view.slug ?? "", name: view.name }, t)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="flex-1" />
        <ToggleGroup
          type="single"
          value={width}
          onValueChange={(next) => next && setWidth(next as PreviewWidth)}
          aria-label={t("viewEditor.previewWidth")}
        >
          {WIDTHS.map(({ width: each, icon: Icon }) => (
            <ToggleGroupItem
              key={each}
              value={each}
              aria-label={t(`viewEditor.width.${each}`)}
              className="h-8 w-8"
            >
              <Icon className="h-4 w-4" />
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={t("viewEditor.undo")}
          disabled={history.past.length === 0}
          onClick={() => dispatch({ type: "undo" })}
        >
          <Undo2 className="h-4 w-4" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={t("viewEditor.redo")}
          disabled={history.future.length === 0}
          onClick={() => dispatch({ type: "redo" })}
        >
          <Redo2 className="h-4 w-4" />
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={!dirty || put.isPending}
          onClick={() => dispatch({ type: "reset", views: saved })}
        >
          {t("viewEditor.discard")}
        </Button>
        <Button type="button" size="sm" disabled={!dirty || put.isPending} onClick={save}>
          {put.isPending ? t("viewEditor.saving") : t("common:save")}
        </Button>
      </header>
      {current ? (
        <div className="grid min-h-0 flex-1 grid-cols-[16rem_minmax(0,1fr)_18rem]">
          <aside className="min-h-0 border-r">
            <ViewOutline
              view={{
                ...current,
                name: viewName({ slug: current.slug ?? "", name: current.name }, t),
              }}
              fields={fields}
              plugins={plugins}
              selected={selected}
              onSelect={setSelected}
              onChange={changeDefinition}
            />
          </aside>
          <main className="min-h-0">
            <ViewCanvas
              projectId={projectId}
              initiativeId={initiativeId}
              statuses={statuses}
              view={current}
              width={width}
              selected={selected}
              onSelect={setSelected}
            />
          </main>
          <aside className="min-h-0 overflow-y-auto border-l">
            <ViewSettingsPanel
              view={current}
              fields={fields}
              selected={selected}
              onChange={changeDefinition}
              onRename={(name) => change((view) => ({ ...view, name }))}
              onMakeDefault={() =>
                dispatch({
                  type: "change",
                  views: views.map((view, index) => ({ ...view, is_default: index === active })),
                })
              }
              onSelect={setSelected}
            />
          </aside>
        </div>
      ) : null}
      <ConfirmDialog
        open={asking || blocker.status === "blocked"}
        onOpenChange={(open) => {
          if (open) return;
          setAsking(false);
          blocker.reset?.();
        }}
        title={t("viewEditor.unsavedTitle")}
        description={t("viewEditor.unsavedBody")}
        confirmLabel={t("viewEditor.leave")}
        cancelLabel={t("viewEditor.stay")}
        onConfirm={() => {
          leaving.current = true;
          setAsking(false);
          if (blocker.status === "blocked") blocker.proceed?.();
          else onClose();
        }}
        destructive
      />
    </div>
  );
};
