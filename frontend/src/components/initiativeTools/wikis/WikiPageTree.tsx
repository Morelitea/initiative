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
import { CircleChevronRight, Home } from "lucide-react";
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
 * The indent, and the line down it.
 *
 * One rule for every level, pages and headings alike, taken from the initiative
 * section: a child list is inset by `ml-3` and carries a `border-l` in the
 * wiki's own colour. Depth comes from the nesting and from nothing else — no
 * row multiplies a step by its depth, which is what previously left three
 * indents stacking on top of each other.
 */
const BRANCH = "ml-3 space-y-0.5 border-l";

/**
 * One heading of the open page.
 *
 * A button rather than a link: a heading has no address of its own, and this
 * scrolls the page already on screen to it. Drawn muted and iconless so a
 * glance separates what is on this page from the pages under it.
 */
const WikiHeadingRow = ({
  node,
  accentColor,
  onSelect,
}: {
  node: OutlineNode;
  accentColor?: string | null;
  onSelect: (key: string) => void;
}) => (
  <SidebarMenuItem>
    <SidebarMenuButton
      size="sm"
      className="min-w-0 text-muted-foreground hover:text-foreground"
      onClick={() => onSelect(node.key)}
    >
      <span className="min-w-0 flex-1 truncate text-left">{node.text}</span>
    </SidebarMenuButton>
    {node.children.length > 0 ? (
      <div className={BRANCH} style={{ borderColor: accentColor || undefined }}>
        <SidebarMenu>
          {node.children.map((child) => (
            <WikiHeadingRow
              key={child.key}
              node={child}
              accentColor={accentColor}
              onSelect={onSelect}
            />
          ))}
        </SidebarMenu>
      </div>
    ) : null}
  </SidebarMenuItem>
);

/**
 * One page, and everything filed under it.
 *
 * The same shape an initiative section has, at every level: the title is the
 * collapse point, the disclosure beside it turns that branch and nothing else,
 * and what is inside sits behind the guide line. A page with sub-pages
 * collapses whether it is at the root or six deep — there is no level that is
 * merely indented.
 *
 * Under the page being read, its own headings come first: what is *on* this
 * page, before what is beneath it.
 *
 * Declared at module scope rather than inside {@link WikiPageTree}: a component
 * defined during a render is a new type on every render, so React would remount
 * the whole tree each time, and a drag in progress would lose the nodes it is
 * tracking.
 */
const WikiPageRow = ({
  node,
  activePageId,
  homePageId,
  hrefOf,
  renderRowMenu,
  draggableRows,
  showCounts,
  landing,
  isOpen,
  onToggle,
  headings,
  onSelectHeading,
  accentColor,
}: {
  node: WikiTreeNode;
  activePageId?: number | null;
  homePageId?: number | null;
  hrefOf: (page: WikiPageSummary) => string;
  /** What this page's own row offers, drawn at its end. */
  renderRowMenu?: (page: WikiPageSummary) => ReactNode;
  draggableRows: boolean;
  showCounts: boolean;
  landing: Landing | null;
  isOpen: (id: number) => boolean;
  onToggle: (id: number) => void;
  /** The open page's own headings. Empty for every other row. */
  headings: OutlineNode[];
  onSelectHeading: (key: string) => void;
  /** The wiki's colour, worn by the disclosure and the guide line. */
  accentColor?: string | null;
}) => {
  const { t } = useTranslation("wikis");
  const { page, children } = node;
  const active = page.id === activePageId;
  const open = isOpen(page.id);
  // Only the page being read has headings to show; every other row draws its
  // sub-pages alone.
  const ownHeadings = active ? headings : [];
  const expandable = children.length > 0 || ownHeadings.length > 0;
  const showing = landing?.id === page.id ? landing.intent : null;

  const draggable = useDraggable({ id: page.id, disabled: !draggableRows });
  const droppable = useDroppable({ id: page.id, disabled: !draggableRows });
  // One element is both ends of the gesture — what you pick up and what you
  // drop onto — and dnd-kit hands out a ref for each.
  const setRowRef = (node: HTMLElement | null) => {
    draggable.setNodeRef(node);
    droppable.setNodeRef(node);
  };

  return (
    <SidebarMenuItem>
      <Collapsible open={open} onOpenChange={() => onToggle(page.id)}>
        <div
          ref={setRowRef}
          {...draggable.listeners}
          {...draggable.attributes}
          className={cn(
            "group/page flex min-w-0 items-center gap-1 rounded-md",
            draggableRows && "cursor-grab active:cursor-grabbing",
            draggable.isDragging && "opacity-40",
            // Filing it under this page rings the row; placing it beside draws
            // the line it would land on.
            showing === "into" && "ring-1 ring-primary ring-inset",
            showing === "before" && "border-primary border-t-2",
            showing === "after" && "border-primary border-b-2"
          )}
        >
          <div className="flex min-w-0 flex-1 items-center">
            {expandable ? (
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
            ) : (
              <span className="h-7 w-7 shrink-0" />
            )}

            <SidebarMenuButton asChild size="sm" isActive={active} className="min-w-0 flex-1">
              <Link
                to={hrefOf(page)}
                className="flex min-w-0 items-center gap-2"
                title={page.title}
              >
                <span className="min-w-0 flex-1 truncate">{page.title || t("pages.untitled")}</span>
                {page.id === homePageId ? (
                  <Home
                    className="size-3.5 shrink-0 text-muted-foreground"
                    aria-label={t("pages.isHome")}
                  />
                ) : null}
                {showCounts && children.length > 0 ? (
                  <span className="shrink-0 text-muted-foreground text-xs tabular-nums">
                    {children.length}
                  </span>
                ) : null}
              </Link>
            </SidebarMenuButton>
          </div>

          {renderRowMenu ? renderRowMenu(page) : null}
        </div>

        {expandable && open && (
          <CollapsibleContent
            className={BRANCH}
            style={{ borderColor: accentColor || undefined }}
            forceMount
          >
            <SidebarMenu>
              {ownHeadings.map((heading) => (
                <WikiHeadingRow
                  key={heading.key}
                  node={heading}
                  accentColor={accentColor}
                  onSelect={onSelectHeading}
                />
              ))}
              {children.map((child) => (
                <WikiPageRow
                  key={child.page.id}
                  node={child}
                  activePageId={activePageId}
                  homePageId={homePageId}
                  hrefOf={hrefOf}
                  renderRowMenu={renderRowMenu}
                  draggableRows={draggableRows}
                  showCounts={showCounts}
                  landing={landing}
                  isOpen={isOpen}
                  onToggle={onToggle}
                  headings={headings}
                  onSelectHeading={onSelectHeading}
                  accentColor={accentColor}
                />
              ))}
            </SidebarMenu>
          </CollapsibleContent>
        )}
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
  /**
   * What a row offers at its end — drawn by the caller, because what can be
   * done to a page is the caller's business and not the tree's.
   */
  renderRowMenu?: (page: WikiPageSummary) => ReactNode;
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
  renderRowMenu,
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
        <SidebarMenu>
          {tree.map((node) => (
            <WikiPageRow
              key={node.page.id}
              node={node}
              isOpen={isOpen}
              onToggle={toggle}
              activePageId={activePageId}
              homePageId={homePageId}
              hrefOf={hrefOf}
              renderRowMenu={renderRowMenu}
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
