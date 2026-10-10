import { useBlocker } from "@tanstack/react-router";
import { Laptop, Redo2, Smartphone, Tablet, Undo2, X } from "lucide-react";
import { useEffect, useMemo, useReducer, useRef, useState } from "react";
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
import { atLeast, useWidthClass } from "@/hooks/useWidthClass";
import { toast } from "@/lib/mascotToast";
import {
  cardOf,
  changeAt,
  columnsOf,
  historyReducer,
  insertAt,
  moveWithin,
  type NodePath,
  nodeAt,
  pathAfterMove,
  pathAfterRemove,
  type Selection,
  startHistory,
  VIEW_SELECTED,
  withCard,
} from "@/lib/views/draft";
import { pluginFields, usePluginsOnItems } from "@/lib/views/plugins";
import { taskFields } from "@/lib/views/tasks";
import type { ViewNode } from "@/lib/views/tree";

import { type PreviewWidth, ViewCanvas } from "./ViewCanvas";
import { ViewOutline } from "./ViewOutline";
import { ViewSettingsPanel } from "./ViewSettingsPanel";

const WIDTHS: { width: PreviewWidth; icon: typeof Laptop }[] = [
  { width: "desktop", icon: Laptop },
  { width: "tablet", icon: Tablet },
  { width: "phone", icon: Smartphone },
];

/** What can be done to the view open in the editor. Each is one change to
 *  undo, and says what is selected after it. */
export type ViewEdits = {
  select: (selection: Selection) => void;
  setDefinition: (definition: ViewDefinitionInput) => void;
  rename: (name: string) => void;
  makeDefault: () => void;
  movePart: (parent: NodePath, from: number, to: number) => void;
  removePart: (path: NodePath) => void;
  changePart: (path: NodePath, node: ViewNode) => void;
  addPart: (node: ViewNode) => void;
  moveColumn: (from: number, to: number) => void;
  removeColumn: (field: string) => void;
  addColumn: (field: string) => void;
};

/** Where a part is put when it is added: into the group that is selected,
 *  after the part that is, or at the end of the card. */
const placeFor = (card: ViewNode, selection: Selection): { parent: NodePath; index: number } => {
  const end = { parent: [], index: card.children?.length ?? 0 };
  if (selection.kind !== "part") return end;
  const node = nodeAt(card, selection.path);
  if (!node) return end;
  if (node.type === "card" || node.type === "stack") {
    return { parent: selection.path, index: node.children?.length ?? 0 };
  }
  return { parent: selection.path.slice(0, -1), index: (selection.path.at(-1) ?? 0) + 1 };
};

/** Whether a selection still names something in the view, as an undo may
 *  take away what was selected. */
const stillThere = (selection: Selection, definition: ViewDefinitionInput): boolean => {
  if (selection.kind === "part") return nodeAt(cardOf(definition), selection.path) !== undefined;
  if (selection.kind === "column") return columnsOf(definition).includes(selection.field);
  return true;
};

const sameViews = (a: ToolViewWrite[], b: ToolViewWrite[]) =>
  JSON.stringify(a) === JSON.stringify(b);

/**
 * A project's views, edited where they are seen. It takes the whole screen:
 * the views and what can be done to them across the top, the outline of the
 * one open on the left, that view drawn with the project's tasks in the
 * middle, and the settings of what is selected on the right.
 *
 * Every change is a draft until Save, which stores the whole set; readers see
 * the saved views until then. The draft is held against the set as it was
 * last saved (or opened), not against the shared cache a save writes early,
 * so a save under way still counts as unsaved until the server takes it.
 * Nothing changes while a save is under way, and leaving with changes, or
 * during a save, asks first.
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
  const wide = atLeast(useWidthClass(), "md");
  const [base, setBase] = useState(() => viewWrites(set));
  const [history, dispatch] = useReducer(historyReducer, base, startHistory);
  const views = history.present;
  const [active, setActive] = useState(() =>
    Math.max(
      0,
      base.findIndex((view) => (initialSlug ? view.slug === initialSlug : view.is_default))
    )
  );
  const current = views[Math.min(active, views.length - 1)];
  const [selected, setSelected] = useState<Selection>(VIEW_SELECTED);
  const selection = current && stillThere(selected, current.definition) ? selected : VIEW_SELECTED;
  const [width, setWidth] = useState<PreviewWidth>("desktop");
  const dirty = !sameViews(views, base);

  const put = usePutProjectViews(projectId);
  const saving = put.isPending;

  // Someone else's save, read while nothing is changed here, is what the
  // editor starts from. One read mid-edit is set aside: this editor's save
  // replaces the whole set.
  const [seen, setSeen] = useState(set);
  if (seen !== set && !saving) {
    setSeen(set);
    if (!dirty) {
      const fresh = viewWrites(set);
      setBase(fresh);
      dispatch({ type: "reset", views: fresh });
    }
  }

  const { data: definitions = [] } = useProperties({ initiativeId });
  const plugins = usePluginsOnItems(initiativeId);
  const fields = useMemo(
    () => taskFields(definitions, pluginFields(plugins, i18n.language)),
    [definitions, plugins, i18n.language]
  );

  const changeViews = (next: ToolViewWrite[], then?: Selection) => {
    if (saving) return;
    dispatch({ type: "change", views: next });
    if (then) setSelected(then);
  };
  const changeView = (next: (view: ToolViewWrite) => ToolViewWrite, then?: Selection) =>
    changeViews(
      views.map((view, index) => (index === active ? next(view) : view)),
      then
    );
  const changeDefinition = (definition: ViewDefinitionInput, then?: Selection) =>
    changeView((view) => ({ ...view, definition }), then);
  const card = current ? cardOf(current.definition) : null;
  const columns = current ? columnsOf(current.definition) : [];

  const edits: ViewEdits = {
    select: setSelected,
    setDefinition: (definition) => changeDefinition(definition),
    rename: (name) => changeView((view) => ({ ...view, name })),
    makeDefault: () =>
      changeViews(views.map((view, index) => ({ ...view, is_default: index === active }))),
    movePart: (parent, from, to) => {
      if (!card || !current) return;
      changeDefinition(
        withCard(current.definition, moveWithin(card, parent, from, to)),
        selection.kind === "part"
          ? { kind: "part", path: pathAfterMove(selection.path, parent, from, to) }
          : selection
      );
    },
    removePart: (path) => {
      if (!card || !current) return;
      const after = selection.kind === "part" ? pathAfterRemove(selection.path, path) : null;
      changeDefinition(
        withCard(
          current.definition,
          changeAt(card, path, () => null)
        ),
        { kind: "part", path: after ?? path.slice(0, -1) }
      );
    },
    changePart: (path, node) => {
      if (!card || !current) return;
      changeDefinition(
        withCard(
          current.definition,
          changeAt(card, path, () => node)
        )
      );
    },
    addPart: (node) => {
      if (!card || !current) return;
      const { parent, index } = placeFor(card, selection);
      // What was added is selected, to change it at once.
      changeDefinition(withCard(current.definition, insertAt(card, parent, node, index)), {
        kind: "part",
        path: [...parent, index],
      });
    },
    moveColumn: (from, to) => {
      if (!current) return;
      const next = [...columns];
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      changeDefinition({ ...current.definition, columns: next });
    },
    removeColumn: (field) => {
      if (!current) return;
      changeDefinition(
        { ...current.definition, columns: columns.filter((each) => each !== field) },
        VIEW_SELECTED
      );
    },
    addColumn: (field) => {
      if (!current) return;
      changeDefinition(
        { ...current.definition, columns: [...columns, field] },
        { kind: "column", field }
      );
    },
  };

  const save = () =>
    put.mutate(viewSetWrite(set, views), {
      onSuccess: (stored) => {
        const fresh = viewWrites(stored);
        setBase(fresh);
        setSeen(stored);
        dispatch({ type: "reset", views: fresh });
        toast.success(t("viewEditor.saved"));
      },
    });

  // Leaving on purpose (Close after the question) passes.
  const leaving = useRef(false);
  const blocker = useBlocker({
    shouldBlockFn: () => (dirty || saving) && !leaving.current,
    enableBeforeUnload: () => (dirty || saving) && !leaving.current,
    withResolver: true,
  });
  const [asking, setAsking] = useState(false);
  const close = () => {
    if (dirty || saving) setAsking(true);
    else onClose();
  };

  // The keys people already reach for: undo and redo, wherever focus is but
  // a text field, which keeps its own, and never while a save is under way.
  const savingRef = useRef(saving);
  savingRef.current = saving;
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, [contenteditable='true']")) return;
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== "z") return;
      event.preventDefault();
      if (!savingRef.current) dispatch({ type: event.shiftKey ? "redo" : "undo" });
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
          disabled={!wide}
          onValueChange={(value) => {
            setActive(Number(value));
            setSelected(VIEW_SELECTED);
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
          disabled={!wide}
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
          disabled={saving || history.past.length === 0}
          onClick={() => dispatch({ type: "undo" })}
        >
          <Undo2 className="h-4 w-4" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={t("viewEditor.redo")}
          disabled={saving || history.future.length === 0}
          onClick={() => dispatch({ type: "redo" })}
        >
          <Redo2 className="h-4 w-4" />
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={!dirty || saving}
          onClick={() => {
            dispatch({ type: "reset", views: base });
            setSelected(VIEW_SELECTED);
          }}
        >
          {t("viewEditor.discard")}
        </Button>
        <Button type="button" size="sm" disabled={!dirty || saving} onClick={save}>
          {saving ? t("viewEditor.saving") : t("common:save")}
        </Button>
      </header>
      {/* A screen too narrow to edit on keeps the draft, and says so. */}
      {!wide ? (
        <p className="p-6 text-muted-foreground text-sm">{t("viewEditor.compact")}</p>
      ) : current ? (
        <div className="grid min-h-0 flex-1 grid-cols-[16rem_minmax(0,1fr)_18rem]">
          <aside className="min-h-0 border-r">
            <ViewOutline
              view={{
                ...current,
                name: viewName({ slug: current.slug ?? "", name: current.name }, t),
              }}
              fields={fields}
              plugins={plugins}
              selection={selection}
              edits={edits}
              locked={saving}
            />
          </aside>
          <main className="min-h-0">
            <ViewCanvas
              projectId={projectId}
              initiativeId={initiativeId}
              statuses={statuses}
              view={current}
              width={width}
              selection={selection}
              onSelect={setSelected}
            />
          </main>
          <aside className="min-h-0 overflow-y-auto border-l">
            <ViewSettingsPanel
              view={current}
              fields={fields}
              selection={selection}
              edits={edits}
              locked={saving}
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
        description={t(saving ? "viewEditor.savingBody" : "viewEditor.unsavedBody")}
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
