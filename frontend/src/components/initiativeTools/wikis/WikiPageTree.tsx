import {
  DndContext,
  type DragEndEvent,
  type DragMoveEvent,
  type DragStartEvent,
  KeyboardSensor,
  MouseSensor,
  pointerWithin,
  TouchSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import { Link } from "@tanstack/react-router";
import { ChevronRight, FileText, Home, Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { WikiPageSummary } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** A page plus the pages filed under it. Built once from the flat list. */
export interface WikiTreeNode {
  page: WikiPageSummary;
  children: WikiTreeNode[];
}

/**
 * Build the nesting the server deliberately does not send.
 *
 * The API returns pages flat, each naming its parent, because that is the
 * shape a move writes and the shape a lookup wants. The nesting is a view of
 * it, so it is derived here rather than transported.
 *
 * A page whose parent is not in the list is treated as top-level. That happens
 * while a move is in flight, and a page that briefly draws at the root is a far
 * better failure than one that vanishes.
 */
export const buildWikiTree = (pages: WikiPageSummary[]): WikiTreeNode[] => {
  const nodes = new Map<number, WikiTreeNode>(
    pages.map((page) => [page.id, { page, children: [] }])
  );
  const roots: WikiTreeNode[] = [];
  for (const page of pages) {
    const node = nodes.get(page.id);
    if (!node) continue;
    const parent = page.parent_page_id === null ? undefined : nodes.get(page.parent_page_id);
    if (parent) parent.children.push(node);
    else roots.push(node);
  }
  return roots;
};

/** Which of a row's three bands the dragged page is over. */
type DropIntent = "before" | "into" | "after";

/** Where a drag would land, as the tree is drawing it. */
interface Landing {
  id: number;
  intent: DropIntent;
}

/**
 * One row, and the rows filed under it.
 *
 * Declared here rather than inside {@link WikiPageTree}: a component defined
 * during a render is a new type on every render, so React would remount the
 * whole tree each time — and a drag in progress would lose the very nodes it
 * is tracking.
 */
const WikiPageRow = ({
  node,
  depth,
  activePageId,
  homePageId,
  hrefOf,
  onAddChild,
  draggableRows,
  landing,
  isOpen,
  onToggle,
}: {
  node: WikiTreeNode;
  depth: number;
  activePageId?: number | null;
  homePageId?: number | null;
  hrefOf: (page: WikiPageSummary) => string;
  onAddChild?: (parent: WikiPageSummary) => void;
  draggableRows: boolean;
  landing: Landing | null;
  isOpen: (id: number) => boolean;
  onToggle: (id: number) => void;
}) => {
  const { t } = useTranslation("wikis");
  const { page, children } = node;
  const hasChildren = children.length > 0;
  const open = isOpen(page.id);
  const active = page.id === activePageId;
  const showing = landing?.id === page.id ? landing.intent : null;

  const draggable = useDraggable({ id: page.id, disabled: !draggableRows });
  const droppable = useDroppable({ id: page.id, disabled: !draggableRows });

  return (
    <li>
      <div
        ref={droppable.setNodeRef}
        className={cn(
          "group flex items-center gap-0.5 rounded-md pr-1 transition",
          active ? "bg-accent text-accent-foreground" : "hover:bg-accent/50",
          draggable.isDragging && "opacity-40",
          // Filing it under this page highlights the row; placing it beside
          // draws the line it would land on.
          showing === "into" && "ring-1 ring-primary ring-inset",
          showing === "before" && "border-primary border-t-2",
          showing === "after" && "border-primary border-b-2"
        )}
        style={{ paddingLeft: `${depth * 12}px` }}
      >
        {hasChildren ? (
          <button
            type="button"
            onClick={() => onToggle(page.id)}
            className="flex size-5 shrink-0 items-center justify-center rounded text-muted-foreground hover:text-foreground"
            aria-expanded={open}
            aria-label={open ? t("pages.collapse") : t("pages.expand")}
          >
            <ChevronRight
              className={cn("size-3.5 transition-transform", open && "rotate-90")}
              aria-hidden
            />
          </button>
        ) : (
          <span className="size-5 shrink-0" />
        )}

        <Link
          ref={draggable.setNodeRef}
          to={hrefOf(page)}
          className="flex min-w-0 flex-1 items-center gap-1.5 py-1 text-sm"
          title={page.title}
          {...draggable.listeners}
          {...draggable.attributes}
        >
          {page.id === homePageId ? (
            <Home
              className="size-3.5 shrink-0 text-muted-foreground"
              aria-label={t("pages.isHome")}
            />
          ) : (
            <FileText className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
          )}
          <span className="truncate">{page.title || t("pages.untitled")}</span>
        </Link>

        {onAddChild ? (
          <Button
            variant="ghost"
            size="icon"
            className="size-6 shrink-0 opacity-0 transition focus-visible:opacity-100 group-hover:opacity-100"
            onClick={() => onAddChild(page)}
            aria-label={t("pages.newSubPage")}
          >
            <Plus className="size-3.5" aria-hidden />
          </Button>
        ) : null}
      </div>

      {hasChildren && open ? (
        <ul className="space-y-px">
          {children.map((child) => (
            <WikiPageRow
              key={child.page.id}
              node={child}
              depth={depth + 1}
              activePageId={activePageId}
              homePageId={homePageId}
              hrefOf={hrefOf}
              onAddChild={onAddChild}
              draggableRows={draggableRows}
              landing={landing}
              isOpen={isOpen}
              onToggle={onToggle}
            />
          ))}
        </ul>
      ) : null}
    </li>
  );
};

interface WikiPageTreeProps {
  pages: WikiPageSummary[];
  /** Which page is open, so the tree can mark it and open its ancestors. */
  activePageId?: number | null;
  /** The wiki's chosen home page, marked so it reads as the way in. */
  homePageId?: number | null;
  /** Builds the link for a page. The tree does not know the route shape. */
  hrefOf: (page: WikiPageSummary) => string;
  /** Offered per row when the reader may write. Omitted otherwise. */
  onAddChild?: (parent: WikiPageSummary) => void;
  /**
   * Where a dragged page was dropped. Omitted when the reader may not write,
   * which is also what makes the rows undraggable.
   */
  onMove?: (page: WikiPageSummary, parentPageId: number | null, position: number) => void;
  className?: string;
}

/**
 * A wiki's pages, as the tree they sit in.
 *
 * Rows are links rather than buttons — a page is an address, and opening one
 * in a new tab is something people do with a handbook — and the disclosure
 * triangle is a separate control so that following a link and expanding its
 * children are never the same click.
 *
 * Dragging goes through dnd-kit, the same library every other draggable list
 * here uses, so a page moves under a pointer, a finger or the keyboard alike.
 * A tree is not a sortable list though: dropping ON a row files the page under
 * it and dropping at a row's edge places it beside, so rows are plain
 * draggable/droppable pairs rather than a `SortableContext`.
 */
export const WikiPageTree = ({
  pages,
  activePageId,
  homePageId,
  hrefOf,
  onAddChild,
  onMove,
  className,
}: WikiPageTreeProps) => {
  const { t } = useTranslation("wikis");
  const tree = useMemo(() => buildWikiTree(pages), [pages]);

  // The ancestors of the open page. A branch somebody collapsed is forced back
  // open when the page they navigate to lives inside it — otherwise following a
  // link from the body would appear to do nothing.
  const ancestors = useMemo(() => {
    const byId = new Map(pages.map((page) => [page.id, page]));
    const chain = new Set<number>();
    let current = activePageId == null ? undefined : byId.get(activePageId);
    while (current?.parent_page_id != null) {
      chain.add(current.parent_page_id);
      current = byId.get(current.parent_page_id);
    }
    return chain;
  }, [pages, activePageId]);

  // Expanded is the default — a wiki is a thing you skim — so this records the
  // branches somebody has deliberately folded away.
  const [collapsed, setCollapsed] = useState<ReadonlySet<number>>(new Set());
  const isOpen = (id: number) => !collapsed.has(id) || ancestors.has(id);

  const toggle = (id: number) =>
    setCollapsed((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  // The same activation distances the guild rail uses, so a drag started
  // anywhere in the sidebar feels the same.
  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { distance: 8 } }),
    useSensor(KeyboardSensor)
  );

  const [dragging, setDragging] = useState<number | null>(null);
  const [landing, setLanding] = useState<Landing | null>(null);

  /** Every page beneath a given one, by walking the flat list once. */
  const descendantsOf = useMemo(() => {
    const byParent = new Map<number | null, WikiPageSummary[]>();
    for (const page of pages) {
      const siblings = byParent.get(page.parent_page_id) ?? [];
      siblings.push(page);
      byParent.set(page.parent_page_id, siblings);
    }
    return (rootId: number): Set<number> => {
      const found = new Set<number>();
      const frontier = [rootId];
      while (frontier.length > 0) {
        const id = frontier.pop();
        if (id === undefined) continue;
        for (const child of byParent.get(id) ?? []) {
          if (found.has(child.id)) continue;
          found.add(child.id);
          frontier.push(child.id);
        }
      }
      return found;
    };
  }, [pages]);

  /** A section cannot be filed inside itself. The server refuses it too. */
  const canDrop = (dragId: number, targetId: number): boolean =>
    dragId !== targetId && !descendantsOf(dragId).has(targetId);

  /**
   * Read the intent off where the dragged row now sits.
   *
   * The middle half of a row files the page under it; the quarter at each edge
   * places it before or after as a sibling.
   */
  const landingOf = (event: DragMoveEvent): Landing | null => {
    const over = event.over;
    const moving = event.active.rect.current.translated;
    if (!over || !moving) return null;
    const targetId = Number(over.id);
    if (!Number.isFinite(targetId)) return null;
    if (dragging !== null && !canDrop(dragging, targetId)) return null;

    const centre = moving.top + moving.height / 2;
    const offset = (centre - over.rect.top) / over.rect.height;
    if (offset < 0.25) return { id: targetId, intent: "before" };
    if (offset > 0.75) return { id: targetId, intent: "after" };
    return { id: targetId, intent: "into" };
  };

  const onDragStart = (event: DragStartEvent) => setDragging(Number(event.active.id));

  const onDragMove = (event: DragMoveEvent) => {
    const next = landingOf(event);
    if (next?.id !== landing?.id || next?.intent !== landing?.intent) {
      setLanding(next);
    }
  };

  const clearDrag = () => {
    setDragging(null);
    setLanding(null);
  };

  const onDragEnd = (event: DragEndEvent) => {
    const page = pages.find((candidate) => candidate.id === Number(event.active.id));
    const dropped = landing;
    clearDrag();
    if (!onMove || !page || !dropped) return;

    const target = pages.find((candidate) => candidate.id === dropped.id);
    if (!target || !canDrop(page.id, target.id)) return;

    if (dropped.intent === "into") {
      const childCount = pages.filter((p) => p.parent_page_id === target.id).length;
      onMove(page, target.id, childCount);
      return;
    }
    // A sibling drop: its index among the target's siblings, counted without
    // the page being moved so the number means the same before and after.
    const siblings = pages.filter(
      (p) => p.parent_page_id === target.parent_page_id && p.id !== page.id
    );
    const index = siblings.findIndex((p) => p.id === target.id);
    onMove(page, target.parent_page_id, dropped.intent === "before" ? index : index + 1);
  };

  if (pages.length === 0) {
    return (
      <p className={cn("px-2 py-1.5 text-muted-foreground text-sm", className)}>
        {t("pages.empty")}
      </p>
    );
  }

  return (
    <nav className={className} aria-label={t("pages.title")}>
      <DndContext
        sensors={sensors}
        collisionDetection={pointerWithin}
        onDragStart={onDragStart}
        onDragMove={onDragMove}
        onDragEnd={onDragEnd}
        onDragCancel={clearDrag}
      >
        <ul className="space-y-px">
          {tree.map((node) => (
            <WikiPageRow
              key={node.page.id}
              node={node}
              depth={0}
              activePageId={activePageId}
              homePageId={homePageId}
              hrefOf={hrefOf}
              onAddChild={onAddChild}
              draggableRows={Boolean(onMove)}
              landing={landing}
              isOpen={isOpen}
              onToggle={toggle}
            />
          ))}
        </ul>
      </DndContext>
    </nav>
  );
};
