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
import { CircleChevronRight, FileText, GripVertical, Home, Plus } from "lucide-react";
import { type ReactNode, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { WikiPageSummary } from "@/api/generated/initiativeAPI.schemas";
import {
  type OutlineNode,
  useOutlineNavigate,
  useOutlineNodes,
} from "@/components/documents/DocumentOutline";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { SidebarMenu, SidebarMenuButton, SidebarMenuItem } from "@/components/ui/sidebar";
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
 * One step of indent. Depth is drawn with this and nothing else — the row at
 * depth three is three steps in, whether it is a page or a heading — so there
 * is one ruler down the tree instead of one per kind of row.
 */
const STEP = 12;

/** A row of the flattened list: what to draw, and how far in. */
interface Row {
  kind: "page" | "heading";
  key: string;
  depth: number;
  page?: WikiTreeNode;
  heading?: OutlineNode;
}

/** Every heading of the open page, flattened to rows at increasing depth. */
const headingRows = (nodes: OutlineNode[], depth: number): Row[] =>
  nodes.flatMap((node) => [
    { kind: "heading" as const, key: `h-${node.key}`, depth, heading: node },
    ...headingRows(node.children, depth + 1),
  ]);

/**
 * Everything under a top-level page, in reading order.
 *
 * A sub-page is not its own nest surface: only the top-level page collapses,
 * and everything inside it is one list that indents. Two collapsing levels was
 * the thing that made this unreadable — a branch inside a branch, each with its
 * own line, and no way to tell at a glance how deep anything was.
 *
 * The open page's own headings sit immediately under it, one step further in,
 * because they are what is *on* that page.
 */
const descendantRows = (
  nodes: WikiTreeNode[],
  depth: number,
  activePageId: number | null | undefined,
  headings: OutlineNode[]
): Row[] =>
  nodes.flatMap((node) => [
    { kind: "page" as const, key: `p-${node.page.id}`, depth, page: node },
    ...(node.page.id === activePageId ? headingRows(headings, depth + 1) : []),
    ...descendantRows(node.children, depth + 1, activePageId, headings),
  ]);

/**
 * One heading of the open page.
 *
 * A button rather than a link: a heading has no address of its own, and this
 * scrolls the page already on screen to it. Drawn muted and iconless so a
 * glance separates what is on this page from the pages under it.
 */
const WikiHeadingRow = ({
  node,
  depth,
  onSelect,
}: {
  node: OutlineNode;
  depth: number;
  onSelect: (key: string) => void;
}) => (
  <SidebarMenuItem style={{ paddingLeft: depth * STEP }}>
    <SidebarMenuButton
      size="sm"
      className="min-w-0 text-muted-foreground hover:text-foreground"
      onClick={() => onSelect(node.key)}
    >
      <span className="min-w-0 flex-1 truncate text-left">{node.text}</span>
    </SidebarMenuButton>
  </SidebarMenuItem>
);

/**
 * One page, as a row.
 *
 * The same parts an initiative's rows are made of. Whether it collapses is not
 * its own business: a top-level page is handed the disclosure, and a page
 * inside one is handed an indent.
 *
 * Declared at module scope rather than inside {@link WikiPageTree}: a component
 * defined during a render is a new type on every render, so React would remount
 * the whole tree each time, and a drag in progress would lose the nodes it is
 * tracking.
 */
const WikiPageRow = ({
  node,
  depth,
  activePageId,
  homePageId,
  hrefOf,
  onAddChild,
  draggableRows,
  showCounts,
  landing,
  disclosure,
}: {
  node: WikiTreeNode;
  depth: number;
  activePageId?: number | null;
  homePageId?: number | null;
  hrefOf: (page: WikiPageSummary) => string;
  onAddChild?: (parent: WikiPageSummary) => void;
  draggableRows: boolean;
  showCounts: boolean;
  landing: Landing | null;
  /** The chevron, for the one level that has one. A spacer keeps the rest aligned. */
  disclosure?: ReactNode;
}) => {
  const { t } = useTranslation("wikis");
  const { page, children } = node;
  const active = page.id === activePageId;
  const showing = landing?.id === page.id ? landing.intent : null;

  const draggable = useDraggable({ id: page.id, disabled: !draggableRows });
  const droppable = useDroppable({ id: page.id, disabled: !draggableRows });

  return (
    <div
      ref={droppable.setNodeRef}
      className={cn(
        "group/page flex min-w-0 items-center gap-1 rounded-md",
        draggable.isDragging && "opacity-40",
        // Filing it under this page rings the row; placing it beside draws the
        // line it would land on.
        showing === "into" && "ring-1 ring-primary ring-inset",
        showing === "before" && "border-primary border-t-2",
        showing === "after" && "border-primary border-b-2"
      )}
      style={{ marginLeft: depth * STEP }}
    >
      <div className="flex min-w-0 flex-1 items-center">
        {disclosure ?? <span className="h-7 w-7 shrink-0" />}

        <SidebarMenuButton asChild size="sm" isActive={active} className="min-w-0 flex-1">
          <Link to={hrefOf(page)} className="flex min-w-0 items-center gap-2" title={page.title}>
            {page.id === homePageId ? (
              <Home className="h-4 w-4 shrink-0" aria-label={t("pages.isHome")} />
            ) : (
              <FileText className="h-4 w-4 shrink-0" aria-hidden />
            )}
            <span className="min-w-0 flex-1 truncate">{page.title || t("pages.untitled")}</span>
            {showCounts && children.length > 0 ? (
              <span className="shrink-0 text-muted-foreground text-xs tabular-nums">
                {children.length}
              </span>
            ) : null}
          </Link>
        </SidebarMenuButton>
      </div>

      {/* Dragging has its own grip. The row is a link, and a link that is also
          the drag handle cannot be clicked without starting a gesture first.
          Revealed on hover, the way the initiative row reveals its settings. */}
      {draggableRows ? (
        <Button
          ref={draggable.setNodeRef}
          variant="ghost"
          size="icon"
          className="hidden h-6 w-0 shrink-0 cursor-grab overflow-hidden p-0 opacity-0 transition-all focus-visible:w-6 focus-visible:opacity-100 group-hover/page:w-6 group-hover/page:opacity-100 motion-reduce:transition-none lg:flex"
          aria-label={t("pages.reorder")}
          {...draggable.listeners}
          {...draggable.attributes}
        >
          <GripVertical className="size-3.5" aria-hidden />
        </Button>
      ) : null}

      {onAddChild ? (
        <Button
          variant="ghost"
          size="icon"
          className="size-6 shrink-0 opacity-0 transition focus-visible:opacity-100 group-hover/page:opacity-100"
          onClick={() => onAddChild(page)}
          aria-label={t("pages.newSubPage")}
        >
          <Plus className="size-3.5" aria-hidden />
        </Button>
      ) : null}
    </div>
  );
};

/**
 * A top-level page and everything filed under it.
 *
 * This is the only thing in the tree that opens and shuts, and the only place
 * a guide line is drawn. Inside it is one flat list in reading order: each
 * sub-page one step further in, and the open page's headings under it.
 */
const WikiSection = ({
  node,
  open,
  onToggle,
  activePageId,
  homePageId,
  hrefOf,
  onAddChild,
  draggableRows,
  showCounts,
  landing,
  headings,
  onSelectHeading,
  accentColor,
}: {
  node: WikiTreeNode;
  open: boolean;
  onToggle: () => void;
  activePageId?: number | null;
  homePageId?: number | null;
  hrefOf: (page: WikiPageSummary) => string;
  onAddChild?: (parent: WikiPageSummary) => void;
  draggableRows: boolean;
  showCounts: boolean;
  landing: Landing | null;
  headings: OutlineNode[];
  onSelectHeading: (key: string) => void;
  /** The wiki's own colour, worn by the disclosure and the guide line. */
  accentColor?: string | null;
}) => {
  const { t } = useTranslation("wikis");
  const active = node.page.id === activePageId;
  const rows = [
    ...(active ? headingRows(headings, 0) : []),
    ...descendantRows(node.children, 0, activePageId, headings),
  ];

  return (
    <SidebarMenuItem>
      <Collapsible open={open} onOpenChange={onToggle}>
        <WikiPageRow
          node={node}
          depth={0}
          activePageId={activePageId}
          homePageId={homePageId}
          hrefOf={hrefOf}
          onAddChild={onAddChild}
          draggableRows={draggableRows}
          showCounts={showCounts}
          landing={landing}
          disclosure={
            rows.length > 0 ? (
              <CollapsibleTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 shrink-0"
                  aria-label={open ? t("pages.collapse") : t("pages.expand")}
                >
                  <CircleChevronRight
                    className={cn("h-4 w-4 transition-transform", open && "rotate-90")}
                    style={{ color: accentColor || undefined }}
                  />
                </Button>
              </CollapsibleTrigger>
            ) : undefined
          }
        />

        {rows.length > 0 ? (
          <CollapsibleContent
            className="ml-3 space-y-0.5 border-l"
            style={{ borderColor: accentColor || undefined }}
          >
            <SidebarMenu>
              {rows.map((row) =>
                row.kind === "heading" && row.heading ? (
                  <WikiHeadingRow
                    key={row.key}
                    node={row.heading}
                    depth={row.depth}
                    onSelect={onSelectHeading}
                  />
                ) : row.page ? (
                  <SidebarMenuItem key={row.key}>
                    <WikiPageRow
                      node={row.page}
                      depth={row.depth}
                      activePageId={activePageId}
                      homePageId={homePageId}
                      hrefOf={hrefOf}
                      onAddChild={onAddChild}
                      draggableRows={draggableRows}
                      showCounts={showCounts}
                      landing={landing}
                    />
                  </SidebarMenuItem>
                ) : null
              )}
            </SidebarMenu>
          </CollapsibleContent>
        ) : null}
      </Collapsible>
    </SidebarMenuItem>
  );
};

interface WikiPageTreeProps {
  pages: WikiPageSummary[];
  /** Which page is open, so the tree can mark it and open its ancestors. */
  activePageId?: number | null;
  /** The wiki's chosen home page, marked so it reads as the way in. */
  homePageId?: number | null;
  /** Whether a row says how many pages sit under it — the wiki's own choice. */
  showCounts?: boolean;
  /** The wiki's accent, so its branches read as its own the way an initiative's do. */
  accentColor?: string | null;
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
 * Built out of the same parts an initiative's section is, so moving around a
 * wiki feels like moving around anything else in this column: a disclosure
 * that turns the branch, a link that opens the page, and children inset behind
 * a guide line.
 *
 * Rows are links rather than buttons — a page is an address, and opening one
 * in a new tab is something people do with a handbook. Dragging is a separate
 * grip for the same reason: the row's job is to be clicked.
 *
 * A tree is not a sortable list, so rows are plain draggable/droppable pairs
 * rather than a `SortableContext`: dropping ON a row files the page under it
 * and dropping at a row's edge places it beside.
 */
export const WikiPageTree = ({
  pages,
  activePageId,
  homePageId,
  hrefOf,
  onAddChild,
  onMove,
  showCounts = false,
  accentColor,
  className,
}: WikiPageTreeProps) => {
  const { t } = useTranslation("wikis");
  const tree = useMemo(() => buildWikiTree(pages), [pages]);
  // The headings the open page's editor is reporting. Empty on every screen
  // that has no editor mounted, which is what makes this safe to read here.
  const headings = useOutlineNodes();
  const goToHeading = useOutlineNavigate();

  // The section the open page lives in. One somebody collapsed is forced back
  // open when they navigate into it — otherwise following a link from the body
  // would appear to do nothing.
  const openSection = useMemo(() => {
    const byId = new Map(pages.map((page) => [page.id, page]));
    let current = activePageId == null ? undefined : byId.get(activePageId);
    while (current?.parent_page_id != null) {
      current = byId.get(current.parent_page_id);
    }
    return current?.id ?? null;
  }, [pages, activePageId]);

  // Expanded is the default — a wiki is a thing you skim — so this records the
  // branches somebody has deliberately folded away.
  const [collapsed, setCollapsed] = useState<ReadonlySet<number>>(new Set());
  const isOpen = (id: number) => !collapsed.has(id) || id === openSection;

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
        <SidebarMenu>
          {tree.map((node) => (
            <WikiSection
              key={node.page.id}
              node={node}
              open={isOpen(node.page.id)}
              onToggle={() => toggle(node.page.id)}
              activePageId={activePageId}
              homePageId={homePageId}
              hrefOf={hrefOf}
              onAddChild={onAddChild}
              draggableRows={Boolean(onMove)}
              showCounts={showCounts}
              landing={landing}
              headings={headings}
              onSelectHeading={goToHeading}
              accentColor={accentColor}
            />
          ))}
        </SidebarMenu>
      </DndContext>
    </nav>
  );
};
