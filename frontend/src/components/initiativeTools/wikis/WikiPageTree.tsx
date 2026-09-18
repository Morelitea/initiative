import {
  DndContext,
  type DragEndEvent,
  type DragMoveEvent,
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
import { CircleChevronRight, FileText, Home } from "lucide-react";
import { type ReactNode, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type WikiPageHeading,
  WikiPageKind,
  type WikiPageSummary,
} from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { SidebarMenu, SidebarMenuButton, SidebarMenuItem } from "@/components/ui/sidebar";
import { cn } from "@/lib/utils";

/** Which side of a row a dragged page would land on. */
type DropIntent = "before" | "after";

/** Where a drag would land, as the list is drawing it. */
interface Landing {
  id: number;
  intent: DropIntent;
}

/**
 * The indent, and the line down it.
 *
 * One rule for every level, taken from the initiative section: a child list is
 * inset by `ml-3` and carries a `border-l` in the wiki's own colour. Depth
 * comes from the nesting and from nothing else.
 */
const BRANCH = "ml-3 space-y-0.5 border-l";

/** A heading, and the headings written under it. */
interface HeadingNode {
  heading: WikiPageHeading;
  children: HeadingNode[];
}

/**
 * A page's headings as a tree.
 *
 * The server sends them flat and in order; the nesting is inferred from the
 * levels alone. A shallower heading closes every deeper one still open, so a
 * page that starts at `h2` puts its `h2`s at the top level, and one that jumps
 * `h1` to `h3` files the `h3` under the `h1` rather than inventing an empty
 * `h2` to sit between them.
 */
export const buildHeadingTree = (headings: readonly WikiPageHeading[]): HeadingNode[] => {
  const roots: HeadingNode[] = [];
  const open: HeadingNode[] = [];

  for (const heading of headings) {
    const node: HeadingNode = { heading, children: [] };
    while (open.length > 0 && open[open.length - 1].heading.level >= heading.level) {
      open.pop();
    }
    const parent = open[open.length - 1];
    if (parent) parent.children.push(node);
    else roots.push(node);
    open.push(node);
  }
  return roots;
};

/**
 * One heading of a page.
 *
 * A link rather than a button: a heading has an address — its page, plus the
 * anchor the editor stamps on it when it renders — so it can be opened from a
 * page you are not currently on, and opened in a new tab like anything else.
 */
const WikiHeadingRow = ({
  node,
  href,
  hrefOf,
  accentColor,
}: {
  node: HeadingNode;
  href: string;
  hrefOf: (anchor: string) => string;
  accentColor?: string | null;
}) => (
  <SidebarMenuItem>
    <SidebarMenuButton asChild size="sm" className="min-w-0 text-muted-foreground">
      <Link to={hrefOf(node.heading.anchor)} className="min-w-0">
        <span className="min-w-0 flex-1 truncate text-left">{node.heading.text}</span>
      </Link>
    </SidebarMenuButton>
    {node.children.length > 0 ? (
      <div className={BRANCH} style={{ borderColor: accentColor || undefined }}>
        <SidebarMenu>
          {node.children.map((child) => (
            <WikiHeadingRow
              key={child.heading.anchor}
              node={child}
              href={href}
              hrefOf={hrefOf}
              accentColor={accentColor}
            />
          ))}
        </SidebarMenu>
      </div>
    ) : null}
  </SidebarMenuItem>
);

/**
 * One page, and — while you are reading it — what is on it.
 *
 * A wiki's pages do not nest: the structure of a wiki is the pages beside each
 * other and the headings inside each one. So a row's disclosure opens its
 * headings, which is the only thing a page contains.
 *
 * The parts are an initiative row's: the same chevron, the same guide line, and
 * a title that is a link because a page is an address.
 *
 * Declared at module scope rather than inside {@link WikiPageTree}: a component
 * defined during a render is a new type on every render, so React would remount
 * the list each time, and a drag in progress would lose the rows it is tracking.
 */
const WikiPageRow = ({
  page,
  active,
  isHome,
  href,
  draggable: draggableRows,
  landing,
  open,
  onToggle,
  accentColor,
  rowMenu,
}: {
  page: WikiPageSummary;
  active: boolean;
  isHome: boolean;
  href: string;
  draggable: boolean;
  landing: Landing | null;
  open: boolean;
  onToggle: () => void;
  accentColor?: string | null;
  rowMenu?: ReactNode;
}) => {
  const { t } = useTranslation("wikis");
  const showing = landing?.id === page.id ? landing.intent : null;
  // Every page's headings come with the page, so a row is collapsible from the
  // moment it is drawn — nobody has to open a page to find out that it has
  // anything in it.
  const headings = useMemo(() => buildHeadingTree(page.headings), [page.headings]);
  const expandable = headings.length > 0;

  const movable = draggableRows && page.kind === WikiPageKind.page;
  const draggable = useDraggable({ id: page.id, disabled: !movable });
  const droppable = useDroppable({ id: page.id, disabled: !movable });
  // One element is both ends of the gesture — what you pick up and what you
  // drop onto — and dnd-kit hands out a ref for each.
  const setRowRef = (node: HTMLElement | null) => {
    draggable.setNodeRef(node);
    droppable.setNodeRef(node);
  };

  return (
    <SidebarMenuItem>
      <Collapsible open={open} onOpenChange={onToggle}>
        <div
          ref={setRowRef}
          {...draggable.listeners}
          {...draggable.attributes}
          className={cn(
            "group/page flex min-w-0 items-center gap-1 rounded-md",
            movable && "cursor-grab active:cursor-grabbing",
            draggable.isDragging && "opacity-40",
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
              <Link to={href} className="flex min-w-0 items-center gap-2" title={page.title}>
                {/* A draft reads as unfinished at a glance: only the people who
                    can write here are shown it at all. */}
                <span
                  className={cn(
                    "min-w-0 flex-1 truncate",
                    page.is_draft && "text-muted-foreground"
                  )}
                >
                  {page.title || t("pages.untitled")}
                </span>
                {page.is_draft ? (
                  <span className="shrink-0 rounded border px-1 text-[10px] text-muted-foreground uppercase">
                    {t("pages.draft")}
                  </span>
                ) : null}
                {page.kind === WikiPageKind.document ? (
                  <FileText
                    className="size-3.5 shrink-0 text-muted-foreground"
                    aria-label={t("documents.openDocument")}
                  />
                ) : null}
                {isHome ? (
                  <Home
                    className="size-3.5 shrink-0 text-muted-foreground"
                    aria-label={t("pages.isHome")}
                  />
                ) : null}
              </Link>
            </SidebarMenuButton>
          </div>

          {rowMenu}
        </div>

        {expandable ? (
          <CollapsibleContent
            className={BRANCH}
            style={{ borderColor: accentColor || undefined }}
            forceMount
          >
            <SidebarMenu>
              {headings.map((node) => (
                <WikiHeadingRow
                  key={node.heading.anchor}
                  node={node}
                  href={href}
                  hrefOf={(anchor) => `${href}#${anchor}`}
                  accentColor={accentColor}
                />
              ))}
            </SidebarMenu>
          </CollapsibleContent>
        ) : null}
      </Collapsible>
    </SidebarMenuItem>
  );
};

interface WikiPageTreeProps {
  pages: WikiPageSummary[];
  /** Which page is open, so the list can mark it and show what is on it. */
  activePageId?: number | null;
  /** The wiki's chosen home page, marked so it reads as the way in. */
  homePageId?: number | null;
  /** The wiki's accent, so its branches read as its own the way an initiative's do. */
  accentColor?: string | null;
  /** Builds the link for a page. The list does not know the route shape. */
  hrefOf: (page: WikiPageSummary) => string;
  /**
   * What a row offers at its end — drawn by the caller, because what can be
   * done to a page is the caller's business and not this component's.
   */
  renderRowMenu?: (page: WikiPageSummary) => ReactNode;
  /**
   * Where a dragged page was dropped, as its new index in the list. Omitted
   * when the reader may not write, which is also what makes rows undraggable.
   */
  onMove?: (page: WikiPageSummary, position: number) => void;
  className?: string;
}

/**
 * A wiki's pages, and the headings of the one being read.
 *
 * There are no sub-pages. A wiki is a flat list of pages, and the structure
 * people actually write is the headings inside each one — so the nesting in
 * this column comes out of the open page's body rather than out of the table.
 *
 * Rows are links rather than buttons — a page is an address, and opening one in
 * a new tab is something people do with a handbook. The row is also the surface
 * you drag: the sensors want six pixels of travel first, so a click only ever
 * follows the link.
 */
export const WikiPageTree = ({
  pages,
  activePageId,
  homePageId,
  accentColor,
  hrefOf,
  renderRowMenu,
  onMove,
  className,
}: WikiPageTreeProps) => {
  const { t } = useTranslation("wikis");

  // Expanded is the default — a wiki is a thing you skim — so this records the
  // pages somebody has deliberately folded away.
  const [collapsed, setCollapsed] = useState<ReadonlySet<number>>(new Set());
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

  const [landing, setLanding] = useState<Landing | null>(null);

  /** Which half of a row the dragged page now sits over. */
  const landingOf = (event: DragMoveEvent): Landing | null => {
    const over = event.over;
    const moving = event.active.rect.current.translated;
    if (!over || !moving) return null;
    const targetId = Number(over.id);
    if (!Number.isFinite(targetId) || targetId === Number(event.active.id)) return null;

    const centre = moving.top + moving.height / 2;
    const past = centre > over.rect.top + over.rect.height / 2;
    return { id: targetId, intent: past ? "after" : "before" };
  };

  const onDragMove = (event: DragMoveEvent) => {
    const next = landingOf(event);
    if (next?.id !== landing?.id || next?.intent !== landing?.intent) {
      setLanding(next);
    }
  };

  const onDragEnd = (event: DragEndEvent) => {
    const page = pages.find((candidate) => candidate.id === Number(event.active.id));
    const dropped = landing;
    setLanding(null);
    if (!onMove || !page || !dropped) return;

    // Counted without the page being moved, so the index means the same before
    // and after it lands.
    const others = pages.filter((candidate) => candidate.id !== page.id);
    const index = others.findIndex((candidate) => candidate.id === dropped.id);
    if (index < 0) return;
    onMove(page, dropped.intent === "before" ? index : index + 1);
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
        onDragMove={onDragMove}
        onDragEnd={onDragEnd}
        onDragCancel={() => setLanding(null)}
      >
        <SidebarMenu>
          {pages.map((page) => (
            <WikiPageRow
              key={page.id}
              page={page}
              active={page.id === activePageId}
              isHome={page.id === homePageId}
              href={hrefOf(page)}
              draggable={Boolean(onMove)}
              landing={landing}
              open={!collapsed.has(page.id)}
              onToggle={() => toggle(page.id)}
              accentColor={accentColor}
              rowMenu={renderRowMenu?.(page)}
            />
          ))}
        </SidebarMenu>
      </DndContext>
    </nav>
  );
};
