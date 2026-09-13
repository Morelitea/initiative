import {
  ChevronDown,
  ChevronUp,
  GalleryHorizontal,
  LayoutGrid,
  Loader2,
  type LucideIcon,
  Plus,
  Rows3,
  Waypoints,
} from "lucide-react";
import { lazy, type ReactNode, Suspense, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  EndpointRef,
  RelationshipRead,
  SearchSuggestion,
} from "@/api/generated/initiativeAPI.schemas";
import { EntityCard } from "@/components/entities/EntityCard";
import { EntityPicker } from "@/components/entities/EntityPicker";
import { Button } from "@/components/ui/button";
import {
  Carousel,
  CarouselContent,
  CarouselItem,
  CarouselNext,
  CarouselPrevious,
} from "@/components/ui/carousel";
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  type ToolRef,
  useRelate,
  useRelationshipsFor,
  useRelationsNeighbourhood,
  useUnrelate,
} from "@/hooks/useRelationships";
import { toast } from "@/lib/chesterToast";
import {
  canAssert,
  edgeFor,
  groupEdges,
  groupOf,
  RELATION_GROUP_ORDER,
  RELATION_GROUPS,
  type RelationGroup,
  type RelationGroupKey,
} from "@/lib/relationships";
import { getItem, setItem } from "@/lib/storage";

/**
 * The grid every group draws into. `min(…, 100%)` keeps a card from overflowing
 * a container narrower than one column.
 */
/**
 * Fetched when somebody asks for the picture, not before.
 *
 * The graph brings a rendering library and a layout worker with it — around
 * 200KB that a project, a task and a document page would otherwise all carry for
 * a view behind a menu that most readers never open.
 */
const RelationsGraph = lazy(() =>
  import("@/components/entities/RelationsGraph").then((module) => ({
    default: module.RelationsGraph,
  }))
);

const CARD_GRID =
  "grid gap-4 [grid-template-columns:repeat(auto-fill,minmax(min(10rem,100%),1fr))]";

/** Rows stack in one column however wide the section is: a row is read across,
 *  so two of them side by side would be two lists to scan rather than one. */
const ROW_LIST = "flex flex-col gap-1.5";

/**
 * How a section draws what it found.
 *
 * `tiles` and `rows` keep a heading per kind of link. `carousel` and `graph`
 * deliberately do not: a carousel is one shelf you push along, and a graph is
 * one picture — so in both, what a link says is carried on the link itself.
 */
export type RelationsLayout = "tiles" | "rows" | "carousel" | "graph";

const LAYOUT_ICONS: Record<RelationsLayout, LucideIcon> = {
  tiles: LayoutGrid,
  rows: Rows3,
  // Not `GalleryHorizontalEnd`: that one is already the queue's own mark.
  carousel: GalleryHorizontal,
  graph: Waypoints,
};

const LAYOUTS: RelationsLayout[] = ["tiles", "rows", "carousel", "graph"];

const isLayout = (value: unknown): value is RelationsLayout =>
  typeof value === "string" && (LAYOUTS as string[]).includes(value);

interface RelationsSectionProps {
  /** The thing whose links these are. */
  entity: EndpointRef;
  /** Links made here stay inside one initiative, which the server enforces. */
  initiativeId: number | null;
  /**
   * The tool the anchor is addressed inside, so a write also refreshes the
   * tool's own copy of its side of the link. A project is its own tool; a task's
   * is its project.
   */
  anchorTool?: ToolRef | null;
  canEdit: boolean;
  /** Which headings this surface shows. Defaults to all of them. */
  groups?: RelationGroupKey[];
  /** Extra header buttons — a "New document" shortcut, say. */
  headerActions?: ReactNode;
  /** Persist the collapsed state and the chosen density under this key. */
  collapseKey?: string;
  /**
   * How to draw these before anybody says otherwise. Tiles suit a full-width
   * section, rows a column beside a form, a carousel a shelf of attachments.
   */
  defaultLayout?: RelationsLayout;
  /** What the thing itself is called, for the middle of the graph. */
  entityTitle?: string;
  title?: string;
  description?: string;
  className?: string;
}

/**
 * Everything connected to one thing, and the way to connect more.
 *
 * One request asks for every edge touching the thing, and the headings are
 * filters over that one answer — so adding a heading costs nothing. Which
 * heading an edge falls under, what it is called, and which way round asserting
 * one writes it all come from `@/lib/relationships`; this draws the result.
 *
 * A heading with nothing under it is not drawn. Seven empty headings would say
 * less than one line admitting there is nothing here yet.
 */
export const RelationsSection = ({
  entity,
  initiativeId,
  anchorTool,
  canEdit,
  groups = RELATION_GROUP_ORDER,
  headerActions,
  collapseKey,
  defaultLayout = "tiles",
  entityTitle,
  title,
  description,
  className,
}: RelationsSectionProps) => {
  const { t } = useTranslation("relations");
  const [collapsed, setCollapsed] = useState(
    () => Boolean(collapseKey) && getItem(collapseKey as string) === "true"
  );
  // Remembered per surface, like the collapsed state beside it: whoever chose a
  // way of looking at this probably wants it again next time.
  const layoutKey = collapseKey ? `${collapseKey}:layout` : null;
  const [layout, setLayout] = useState<RelationsLayout>(() => {
    const saved = layoutKey ? getItem(layoutKey) : null;
    return isLayout(saved) ? saved : defaultLayout;
  });
  const [adding, setAdding] = useState(false);
  const [groupKey, setGroupKey] = useState<RelationGroupKey | null>(null);
  const [picked, setPicked] = useState<SearchSuggestion | null>(null);
  const [hops, setHops] = useState(1);
  const [showTags, setShowTags] = useState(false);

  const shown = useMemo<RelationGroup[]>(() => groups.map((key) => RELATION_GROUPS[key]), [groups]);
  const assertable = useMemo(() => shown.filter((group) => group.assertable), [shown]);

  // Attaching is what nearly every one of these is, so the dialog opens on it
  // rather than on an empty box somebody has to answer before they can search.
  /**
   * The links that can actually be made to what was picked.
   *
   * Reversing groups — "Blocks", "Has as a part" — assert their edge from the
   * far end, which the server will only accept from somebody who may change it.
   * Offering them for a thing you can only read is offering a refusal.
   */
  const offered = useMemo(
    () => assertable.filter((group) => canAssert(group, picked?.can_write !== false)),
    [assertable, picked]
  );

  const chosenGroup =
    (groupKey && offered.some((group) => group.key === groupKey) ? groupKey : null) ??
    offered[0]?.key ??
    null;

  const { data: rows = [], isLoading, isError } = useRelationshipsFor(entity);
  // Only walked while the picture is the thing on screen: a second hop is a
  // request per neighbour, and no other layout shows more than one.
  const neighbourhood = useRelationsNeighbourhood(entity, hops, {
    enabled: layout === "graph" && !collapsed,
    includeTags: showTags,
  });
  const grouped = useMemo(() => groupEdges(rows, shown), [rows, shown]);

  const closeDialog = () => {
    setAdding(false);
    setGroupKey(null);
    setPicked(null);
  };

  const relate = useRelate(anchorTool, {
    onSuccess: () => {
      toast.success(t("added"));
      closeDialog();
    },
  });
  const unrelate = useUnrelate(anchorTool, {
    onSuccess: () => toast.success(t("removed")),
  });

  const setLayoutState = (next: RelationsLayout) => {
    setLayout(next);
    if (layoutKey) setItem(layoutKey, next);
  };

  const setCollapsedState = (next: boolean) => {
    setCollapsed(next);
    if (collapseKey) setItem(collapseKey, next.toString());
  };

  const submit = () => {
    if (!chosenGroup || !picked) return;
    relate.mutate(
      edgeFor(RELATION_GROUPS[chosenGroup], entity, {
        type: picked.entity_type,
        id: picked.entity_id,
      })
    );
  };

  /**
   * What is actually going to be drawn, not what came back.
   *
   * An edge no shown heading claims — a tag, on a surface that leaves tags to
   * the tag picker — is fetched and then not drawn, so counting the answer
   * would report "some" and then render an empty panel.
   */
  const visible = useMemo(() => rows.filter((row) => groupOf(row, shown) !== null), [rows, shown]);
  const total = visible.length;

  return (
    <Collapsible
      open={!collapsed}
      onOpenChange={(open) => setCollapsedState(!open)}
      className={className ?? "space-y-4 rounded-2xl border bg-card p-5 shadow-sm"}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="inline-flex items-center gap-2">
            <Waypoints className="h-5 w-5 text-muted-foreground" />
            <h2 className="font-semibold text-xl">{title ?? t("title")}</h2>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-8 w-8 rounded-full"
              onClick={() => setCollapsedState(!collapsed)}
              aria-expanded={!collapsed}
              aria-label={title ?? t("title")}
            >
              {collapsed ? <ChevronDown className="h-4 w-4" /> : <ChevronUp className="h-4 w-4" />}
            </Button>
          </div>
          <p className="text-muted-foreground text-sm">{description ?? t("description")}</p>
        </div>
        <div className="flex items-center gap-2">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                aria-label={t("layout.label")}
                title={t("layout.label")}
              >
                {(() => {
                  const Icon = LAYOUT_ICONS[layout];
                  return <Icon className="h-4 w-4" />;
                })()}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {LAYOUTS.map((option) => {
                const Icon = LAYOUT_ICONS[option];
                return (
                  <DropdownMenuItem
                    key={option}
                    onSelect={() => setLayoutState(option)}
                    className={option === layout ? "bg-accent" : undefined}
                  >
                    <Icon className="h-4 w-4" />
                    {t(`layout.${option}`)}
                  </DropdownMenuItem>
                );
              })}
            </DropdownMenuContent>
          </DropdownMenu>
          {headerActions}
          {canEdit && assertable.length > 0 ? (
            <Button type="button" size="sm" variant="outline" onClick={() => setAdding(true)}>
              <Plus className="h-4 w-4" />
              {t("add")}
            </Button>
          ) : null}
        </div>
      </div>

      <CollapsibleContent className="space-y-6 data-[state=closed]:hidden">
        {isLoading ? (
          <div className={layout === "rows" ? ROW_LIST : CARD_GRID}>
            {[0, 1, 2, 3].map((n) => (
              <Skeleton
                key={n}
                className={
                  layout === "rows" ? "h-12 rounded-lg" : "aspect-4/3 rounded-2xl sm:aspect-square"
                }
              />
            ))}
          </div>
        ) : isError ? (
          <p className="text-muted-foreground text-sm">{t("loadFailed")}</p>
        ) : total === 0 ? (
          <p className="text-muted-foreground text-sm">{t("empty")}</p>
        ) : layout === "graph" ? (
          <Suspense fallback={<Skeleton className="h-[28rem] w-full rounded-xl" />}>
            <RelationsGraph
              entity={entity}
              title={entityTitle ?? title ?? t("title")}
              nodes={neighbourhood.nodes}
              edges={neighbourhood.edges}
              groups={showTags ? [...shown, RELATION_GROUPS.tagged] : shown}
              hops={hops}
              onHopsChange={setHops}
              showTags={showTags}
              onShowTagsChange={setShowTags}
              loading={neighbourhood.isLoading}
            />
          </Suspense>
        ) : layout === "carousel" ? (
          /* One shelf rather than a heading per kind of link: a carousel is
             pushed along, and stopping it at every heading would make it four
             short shelves. What each link says rides on its own card. */
          <Carousel className="relative">
            <CarouselContent className="-ml-4">
              {visible.map((edge) => {
                const group = groupOf(edge, shown);
                if (!group) return null;
                return (
                  <CarouselItem key={edge.id} className="basis-40 pl-4 sm:basis-44 lg:basis-48">
                    <EntityCard
                      end={edge.other}
                      badge={t(`groups.${group.key}.title` as const)}
                      linkedAt={edge.created_at}
                      onRemove={
                        canEdit && edge.provenance === "manual"
                          ? () => unrelate.mutate(edge)
                          : undefined
                      }
                      removing={unrelate.isPending}
                    />
                  </CarouselItem>
                );
              })}
            </CarouselContent>
            <CarouselPrevious className="left-0 -translate-x-1/2" />
            <CarouselNext className="right-0 translate-x-1/2" />
          </Carousel>
        ) : (
          shown.map((group) => {
            const edges = grouped.get(group.key) ?? [];
            if (edges.length === 0) return null;
            const GroupIcon = group.icon;
            return (
              <section key={group.key} className="space-y-3">
                <div className="flex items-center gap-2">
                  <GroupIcon className="h-4 w-4 text-muted-foreground" />
                  <h3 className="font-medium text-sm">{t(`groups.${group.key}.title`)}</h3>
                  <span className="text-muted-foreground text-xs">{edges.length}</span>
                </div>
                {group.assertable ? null : (
                  <p className="text-muted-foreground text-xs">{t("derived")}</p>
                )}
                {/* Sized by the container rather than by viewport breakpoints:
                    this section sits full-width on a project page and in a half
                    column beside a task form, and a fixed column count makes a
                    card enormous in the first and cramped in the second.
                    `auto-fill` rather than `auto-fit` so three cards in a wide
                    row stay card-sized instead of stretching to fill it. */}
                <div className={layout === "rows" ? ROW_LIST : CARD_GRID}>
                  {edges.map((edge: RelationshipRead) => (
                    <EntityCard
                      key={edge.id}
                      end={edge.other}
                      variant={layout === "rows" ? "compact" : "card"}
                      linkedAt={edge.created_at}
                      /* A link read out of a body is not one to take back here:
                         editing the words is how it is withdrawn. */
                      onRemove={
                        canEdit && edge.provenance === "manual"
                          ? () => unrelate.mutate(edge)
                          : undefined
                      }
                      removing={unrelate.isPending}
                    />
                  ))}
                </div>
              </section>
            );
          })
        )}
      </CollapsibleContent>

      <Dialog open={adding} onOpenChange={(open) => (open ? setAdding(true) : closeDialog())}>
        <DialogContent className="max-h-screen w-full overflow-y-auto rounded-2xl border bg-card shadow-2xl sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{t("dialog.title")}</DialogTitle>
            <DialogDescription>{t("dialog.description")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="relation-kind">{t("dialog.relationship")}</Label>
              <Select
                value={chosenGroup ?? undefined}
                onValueChange={(value) => setGroupKey(value as RelationGroupKey)}
              >
                <SelectTrigger id="relation-kind">
                  <SelectValue placeholder={t("dialog.relationship")} />
                </SelectTrigger>
                <SelectContent>
                  {offered.map((group) => (
                    <SelectItem key={group.key} value={group.key}>
                      {t(`groups.${group.key}.option`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>{t("dialog.entity")}</Label>
              <EntityPicker
                subject={entity}
                initiativeId={initiativeId}
                value={picked}
                onChange={setPicked}
                disabled={!chosenGroup}
              />
              {picked && offered.length < assertable.length ? (
                <p className="text-muted-foreground text-xs">{t("dialog.readOnlyTarget")}</p>
              ) : null}
            </div>
          </div>
          <DialogFooter>
            <Button
              type="button"
              onClick={submit}
              disabled={relate.isPending || !chosenGroup || !picked}
            >
              {relate.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t("dialog.submitting")}
                </>
              ) : (
                t("dialog.submit")
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Collapsible>
  );
};
