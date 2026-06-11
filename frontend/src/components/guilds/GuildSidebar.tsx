import {
  closestCenter,
  DndContext,
  type DragEndEvent,
  DragOverlay,
  type DragStartEvent,
  KeyboardSensor,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Link, useRouter } from "@tanstack/react-router";
import { ChevronsLeft, ChevronsRight, Clock, Plus } from "lucide-react";
import type { CSSProperties, FormEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { GuildRead } from "@/api/generated/initiativeAPI.schemas";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useSidebar } from "@/components/ui/sidebar";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { type GuildEntry, useGuilds } from "@/hooks/useGuilds";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { guildPath } from "@/lib/guildUrl";
import { getInitials } from "@/lib/initials";
import { cn } from "@/lib/utils";

import { LogoIcon } from "../LogoIcon";
import { GuildContextMenu } from "./GuildContextMenu";

// Swipe tuning — shared feel with the mobile drawer (see ui/sidebar.tsx).
const SWIPE_THRESHOLD = 60; // px to commit an open/close
const SWIPE_ENGAGE = 8; // px before a gesture counts as a horizontal drag
const FLYOUT_TRANSITION_MS = 300; // keep in sync with the inline transform transition

const CreateGuildButton = ({ expanded = false }: { expanded?: boolean }) => {
  const { createGuild, canCreateGuilds, switchGuild } = useGuilds();
  const { t } = useTranslation("guilds");
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  if (!canCreateGuilds) {
    return null;
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const newGuild = await createGuild({ name, description });
      await switchGuild(newGuild.id);
      setOpen(false);
      setName("");
      setDescription("");
    } catch (err) {
      console.error(err);
      const message = getErrorMessage(err, "guilds:unableToCreateGuild");
      setError(message);
      toast.error(message);
    } finally {
      setSubmitting(false);
      router.navigate({ to: "/" });
    }
  };

  const trigger = expanded ? (
    <DialogTrigger asChild>
      <button
        type="button"
        className="flex w-full items-center gap-3 rounded-lg border border-muted-foreground/40 border-dashed px-3 py-2 text-left text-muted-foreground transition hover:bg-muted hover:text-foreground"
      >
        <span className="flex h-10 w-10 shrink-0 items-center justify-center">
          <Plus className="h-5 w-5" />
        </span>
        <span className="truncate font-medium text-sm">{t("createGuild")}</span>
      </button>
    </DialogTrigger>
  ) : (
    <Tooltip>
      <TooltipTrigger>
        <DialogTrigger asChild>
          <Button
            variant="secondary"
            size="icon"
            className="h-12 w-12 rounded-2xl border border-muted-foreground/40 border-dashed bg-transparent text-muted-foreground hover:bg-muted"
            aria-label={t("createGuild")}
          >
            <Plus className="h-5 w-5" />
          </Button>
        </DialogTrigger>
      </TooltipTrigger>
      <TooltipContent side="right" sideOffset={12}>
        <p>{t("createGuild")}</p>
      </TooltipContent>
    </Tooltip>
  );

  return (
    <Dialog open={open} onOpenChange={(next) => !submitting && setOpen(next)}>
      {trigger}
      <DialogContent className="max-h-screen overflow-y-auto bg-card">
        <DialogHeader>
          <DialogTitle>{t("createGuildTitle")}</DialogTitle>
          <DialogDescription>{t("createGuildDescription")}</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="space-y-2">
            <Label htmlFor="guild-name">{t("guildNameLabel")}</Label>
            <Input
              id="guild-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={t("guildNamePlaceholder")}
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="guild-description">{t("descriptionLabel")}</Label>
            <Textarea
              id="guild-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder={t("descriptionPlaceholder")}
              rows={3}
            />
          </div>
          {error ? <p className="text-destructive text-sm">{error}</p> : null}
          <DialogFooter>
            <Button type="submit" disabled={submitting}>
              {submitting ? t("creating") : t("createGuildSubmit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};

export const GuildAvatar = ({
  name,
  icon,
  active,
  size = "md",
}: {
  name: string;
  icon?: string | null;
  active: boolean;
  size?: "sm" | "md";
}) => {
  const initials = useMemo(() => getInitials(name, "G"), [name]);
  return (
    <Avatar className={cn(size === "sm" ? "h-6 w-6" : "h-10 w-10")}>
      {icon ? <AvatarImage src={icon} alt={name} /> : null}
      <AvatarFallback
        className={cn(active && "bg-primary text-primary-foreground", size === "sm" && "text-xs")}
      >
        {initials}
      </AvatarFallback>
    </Avatar>
  );
};

const SortableGuildButton = ({
  guild,
  isActive,
  isHomeMode,
  onSelect,
}: {
  guild: GuildRead;
  isActive: boolean;
  isHomeMode: boolean;
  onSelect: (guildId: number) => void;
}) => {
  const { t } = useTranslation("guilds");
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: guild.id,
  });
  const style: CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
  };
  if (isDragging) {
    style.opacity = 0.4;
  }
  return (
    <GuildContextMenu guild={guild}>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            ref={setNodeRef}
            onClick={() => onSelect(guild.id)}
            className={cn(
              "relative flex h-12 w-12 cursor-grab items-center justify-center rounded-2xl border-3 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:cursor-grabbing",
              isActive
                ? isHomeMode
                  ? "border-transparent bg-muted text-foreground"
                  : "border-primary/60 bg-primary/10 text-primary"
                : "border-transparent bg-muted text-muted-foreground hover:bg-muted/80"
            )}
            aria-label={t("switchTo", { name: guild.name })}
            style={style}
            {...attributes}
            {...listeners}
          >
            {isActive && isHomeMode ? (
              <span
                className="absolute -bottom-2 left-1/2 z-10 mt-1 h-1 w-7 -translate-x-1/2 rounded-full bg-primary/60"
                aria-hidden="true"
              />
            ) : null}
            <GuildAvatar name={guild.name} icon={guild.icon_base64} active={isActive} />
          </button>
        </TooltipTrigger>
        <TooltipContent side="right" sideOffset={12}>
          {guild.name}
        </TooltipContent>
      </Tooltip>
    </GuildContextMenu>
  );
};

const grantMinutesLeft = (expiresAt?: string | null): number | null => {
  if (!expiresAt) return null;
  return Math.max(0, Math.round((new Date(expiresAt).getTime() - Date.now()) / 60000));
};

// A non-draggable switcher button for a guild reached via a temporary PAM
// grant. Visually distinct (dashed border + clock badge) and shows the
// remaining time on hover.
const GrantGuildButton = ({
  guild,
  isActive,
  onSelect,
}: {
  guild: GuildEntry;
  isActive: boolean;
  onSelect: (guildId: number) => void;
}) => {
  const { t } = useTranslation("guilds");
  const left = grantMinutesLeft(guild.grantExpiresAt);
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          onClick={() => onSelect(guild.id)}
          className={cn(
            "relative flex h-12 w-12 items-center justify-center rounded-2xl border-3 border-dashed transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
            isActive
              ? "border-primary/60 bg-primary/10 text-primary"
              : "border-muted-foreground/40 bg-muted text-muted-foreground hover:bg-muted/80"
          )}
          aria-label={t("switchTo", { name: guild.name })}
        >
          <GuildAvatar name={guild.name} icon={guild.icon_base64} active={isActive} />
          <span className="absolute -top-1 -right-1 rounded-full bg-background p-0.5">
            <Clock className="h-3 w-3 text-amber-500" aria-hidden="true" />
          </span>
        </button>
      </TooltipTrigger>
      <TooltipContent side="right" sideOffset={12}>
        <p>{guild.name}</p>
        {/* De-emphasize against the tooltip's own (primary) background — not
            text-muted-foreground, which is tuned for the card background and
            washes out on the colored tooltip. */}
        <p className="text-primary-foreground/80 text-xs">
          {t("temporaryAccess")}
          {left !== null ? ` · ${t("expiresInMinutes", { minutes: left })}` : ""}
        </p>
      </TooltipContent>
    </Tooltip>
  );
};

// Expanded ("Guilds" flyout) row: avatar + name + member count. Member rows are
// drag-reorderable (via SortableGuildRow); touch reorder is press-and-hold so a
// horizontal swipe still closes the flyout. Grant rows pass no drag props.
const GuildRow = ({
  guild,
  isActive,
  isHomeMode,
  onSelect,
  innerRef,
  style,
  dragProps,
}: {
  guild: GuildEntry;
  isActive: boolean;
  isHomeMode: boolean;
  onSelect: (guildId: number) => void;
  innerRef?: (node: HTMLElement | null) => void;
  style?: CSSProperties;
  dragProps?: Record<string, unknown>;
}) => {
  const { t } = useTranslation("guilds");
  const isGrant = guild.accessType === "grant";
  const left = isGrant ? grantMinutesLeft(guild.grantExpiresAt) : null;
  return (
    <GuildContextMenu guild={guild}>
      <button
        type="button"
        ref={innerRef}
        style={style}
        onClick={() => onSelect(guild.id)}
        className={cn(
          "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          isActive && !isHomeMode ? "bg-primary/10 text-primary" : "text-foreground hover:bg-muted"
        )}
        aria-label={t("switchTo", { name: guild.name })}
        {...dragProps}
      >
        <span className="relative shrink-0">
          <GuildAvatar name={guild.name} icon={guild.icon_base64} active={isActive} />
          {isGrant ? (
            <span className="absolute -top-1 -right-1 rounded-full bg-background p-0.5">
              <Clock className="h-3 w-3 text-amber-500" aria-hidden="true" />
            </span>
          ) : null}
        </span>
        <span className="flex min-w-0 flex-col">
          <span className="truncate font-medium text-sm">{guild.name}</span>
          {isGrant ? (
            <span className="truncate text-muted-foreground text-xs">
              {t("temporaryAccess")}
              {left !== null ? ` · ${t("expiresInMinutes", { minutes: left })}` : ""}
            </span>
          ) : (
            <span className="truncate text-muted-foreground text-xs">
              {t("memberCount", { count: guild.member_count })}
            </span>
          )}
        </span>
      </button>
    </GuildContextMenu>
  );
};

// Sortable wrapper for the flyout. Uses a `flyout-` id prefix so its draggable
// ids never collide with the collapsed rail's DndContext, which stays mounted.
const FLYOUT_DRAG_PREFIX = "flyout-";

const SortableGuildRow = ({
  guild,
  isActive,
  isHomeMode,
  onSelect,
}: {
  guild: GuildEntry;
  isActive: boolean;
  isHomeMode: boolean;
  onSelect: (guildId: number) => void;
}) => {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: `${FLYOUT_DRAG_PREFIX}${guild.id}`,
  });
  return (
    <GuildRow
      guild={guild}
      isActive={isActive}
      isHomeMode={isHomeMode}
      onSelect={onSelect}
      innerRef={setNodeRef}
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.4 : undefined,
        cursor: "grab",
      }}
      dragProps={{ ...attributes, ...listeners }}
    />
  );
};

// Drag ids are numeric on the rail and `flyout-<id>` in the flyout; normalize.
const parseGuildId = (id: string | number): number =>
  Number(String(id).replace(FLYOUT_DRAG_PREFIX, ""));

export const GuildSidebar = ({ isHomeMode = false }: { isHomeMode?: boolean }) => {
  const { guilds, activeGuildId, switchGuild, reorderGuilds, canCreateGuilds } = useGuilds();
  const { suppressNextAutoClose, setSwipeCloseLocked } = useSidebar();
  const { t } = useTranslation(["guilds", "nav"]);
  const router = useRouter();
  const [activeDragId, setActiveDragId] = useState<number | null>(null);
  const sensors = useSensors(
    // Mouse reorders on a small drag; touch reorders on press-and-hold so a
    // horizontal swipe is free to open/close the flyout instead of grabbing a
    // guild to reorder it.
    useSensor(MouseSensor, {
      activationConstraint: {
        distance: 6,
      },
    }),
    useSensor(TouchSensor, {
      activationConstraint: {
        delay: 250,
        tolerance: 8,
      },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );
  const draggedGuild = useMemo(
    () => guilds.find((guild) => guild.id === activeDragId) ?? null,
    [guilds, activeDragId]
  );
  // Member guilds are reorderable; grant (temporary) guilds are rendered
  // separately below and are not sortable.
  const memberGuilds = useMemo(
    () => guilds.filter((guild) => guild.accessType !== "grant"),
    [guilds]
  );
  const grantGuilds = useMemo(
    () => guilds.filter((guild) => guild.accessType === "grant"),
    [guilds]
  );

  // --- Expandable "Guilds" flyout state machine (mirrors MobileSidebar) ---
  // `expanded` is the desired state; `render`/`atOpen` decouple mount from the
  // resting position so the close transition can finish before unmount; `drag`
  // overrides position while a finger is down.
  const [expanded, setExpanded] = useState(false);
  const [render, setRender] = useState(false);
  const [atOpen, setAtOpen] = useState(false);
  const [drag, setDrag] = useState<{ base: "open" | "closed"; delta: number } | null>(null);
  const expandedRef = useRef(expanded);
  useEffect(() => {
    expandedRef.current = expanded;
  }, [expanded]);

  const collapse = useCallback(() => setExpanded(false), []);

  useEffect(() => {
    if (expanded) {
      setRender(true);
      const id = requestAnimationFrame(() => setAtOpen(true));
      return () => cancelAnimationFrame(id);
    }
    setAtOpen(false);
    const id = window.setTimeout(() => setRender(false), FLYOUT_TRANSITION_MS);
    return () => clearTimeout(id);
  }, [expanded]);

  // True while a press-and-hold reorder drag is in progress. A fast swipe never
  // activates dnd (its movement exceeds the TouchSensor tolerance before the
  // delay), so this guard only fires for deliberate holds — keeping a held drag
  // from also engaging an open/close swipe.
  const dndActiveRef = useRef(false);

  // Swipe-to-open: a rightward swipe on the collapsed rail pulls the flyout in,
  // following the finger. Reorder is press-and-hold (TouchSensor delay), so a
  // quick horizontal swipe won't grab a guild icon. A leftward swipe is left to
  // bubble (it closes the mobile drawer); a vertical drag scrolls the rail.
  const openGesture = useRef({ x: 0, y: 0, active: false, engaged: false });
  const handleRailTouchStart = (e: React.TouchEvent) => {
    if (expandedRef.current) return;
    const touch = e.touches[0];
    openGesture.current = { x: touch.clientX, y: touch.clientY, active: true, engaged: false };
  };
  const handleRailTouchMove = (e: React.TouchEvent) => {
    // Check this first: a press-and-hold reorder cancels openGesture.active on
    // its first (vertical) move, so this must run even after that early return
    // would have fired. The drawer's swipe-to-close is disabled separately via
    // the sidebar's swipe-close lock (see handleDragStart) — not stopPropagation,
    // which would also starve dnd-kit's own document-level move listener.
    if (dndActiveRef.current) {
      openGesture.current.active = false;
      return;
    }
    const state = openGesture.current;
    if (!state.active) return;
    const touch = e.touches[0];
    const dx = touch.clientX - state.x;
    const dy = touch.clientY - state.y;
    if (!state.engaged) {
      if (Math.abs(dx) <= Math.abs(dy) || dx < 0) {
        state.active = false; // vertical scroll or leftward (drawer close)
        return;
      }
      if (dx < SWIPE_ENGAGE) return;
      state.engaged = true;
      setRender(true);
    }
    e.preventDefault();
    setDrag({ base: "closed", delta: dx });
  };
  const handleRailTouchEnd = (e: React.TouchEvent) => {
    const state = openGesture.current;
    if (!state.active) return;
    state.active = false;
    if (!state.engaged) return;
    const dx = e.changedTouches[0].clientX - state.x;
    setDrag(null);
    if (dx > SWIPE_THRESHOLD) {
      setAtOpen(true);
      setExpanded(true);
    } else {
      setAtOpen(false);
      window.setTimeout(() => {
        if (!expandedRef.current) setRender(false);
      }, FLYOUT_TRANSITION_MS);
    }
  };

  // Swipe-to-close: handlers on the flyout panel itself. stopPropagation keeps
  // a left-swipe here from bubbling up to the mobile drawer's swipe-to-close.
  const closeGesture = useRef({ x: 0, y: 0, active: false, engaged: false });
  const handlePanelTouchStart = (e: React.TouchEvent) => {
    e.stopPropagation();
    const touch = e.touches[0];
    closeGesture.current = { x: touch.clientX, y: touch.clientY, active: true, engaged: false };
  };
  const handlePanelTouchMove = (e: React.TouchEvent) => {
    const state = closeGesture.current;
    if (!state.active) return;
    e.stopPropagation();
    if (dndActiveRef.current) {
      state.active = false; // a reorder drag owns this gesture
      return;
    }
    const touch = e.touches[0];
    const dx = touch.clientX - state.x;
    const dy = touch.clientY - state.y;
    if (!state.engaged) {
      if (Math.abs(dx) <= Math.abs(dy)) return; // let the list scroll vertically
      if (dx > 0) {
        state.active = false; // rightward — not a close
        return;
      }
      if (Math.abs(dx) < SWIPE_ENGAGE) return;
      state.engaged = true;
    }
    e.preventDefault();
    setDrag({ base: "open", delta: dx });
  };
  const handlePanelTouchEnd = (e: React.TouchEvent) => {
    const state = closeGesture.current;
    if (!state.active) return;
    state.active = false;
    e.stopPropagation();
    if (!state.engaged) return;
    const dx = e.changedTouches[0].clientX - state.x;
    setDrag(null);
    if (dx < -SWIPE_THRESHOLD) {
      setAtOpen(false);
      setExpanded(false);
    }
    // Otherwise atOpen stays true and the panel animates back open.
  };

  const handleGuildSwitch = (guildId: number) => {
    setExpanded(false);
    // Always navigate to the guild dashboard
    if (guildId !== activeGuildId) {
      // Switching guilds navigates, but the sidebar should stay open (unlike
      // most navigations, which auto-close it on mobile).
      suppressNextAutoClose();
      void switchGuild(guildId);
    }
    router.navigate({ to: guildPath(guildId, "/") });
  };

  const handleDragStart = useCallback(
    (event: DragStartEvent) => {
      dndActiveRef.current = true;
      // Suspend the mobile drawer's swipe-to-close while reordering so the two
      // gestures don't fight.
      setSwipeCloseLocked(true);
      const draggedId = parseGuildId(event.active.id);
      if (Number.isFinite(draggedId)) {
        setActiveDragId(draggedId);
      }
    },
    [setSwipeCloseLocked]
  );

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      dndActiveRef.current = false;
      setSwipeCloseLocked(false);
      const { active, over } = event;
      setActiveDragId(null);
      if (!over || active.id === over.id) {
        return;
      }
      const activeId = parseGuildId(active.id);
      const overId = parseGuildId(over.id);
      if (!Number.isFinite(activeId) || !Number.isFinite(overId)) {
        return;
      }
      const oldIndex = memberGuilds.findIndex((guild) => guild.id === activeId);
      const newIndex = memberGuilds.findIndex((guild) => guild.id === overId);
      if (oldIndex === -1 || newIndex === -1) {
        return;
      }
      const orderedIds = arrayMove(memberGuilds, oldIndex, newIndex).map((guild) => guild.id);
      reorderGuilds(orderedIds);
    },
    [memberGuilds, reorderGuilds, setSwipeCloseLocked]
  );

  const handleDragCancel = useCallback(() => {
    dndActiveRef.current = false;
    setSwipeCloseLocked(false);
    setActiveDragId(null);
  }, [setSwipeCloseLocked]);

  const panelTransform = drag
    ? `translateX(clamp(-100%, calc(${drag.base === "open" ? "0%" : "-100%"} + ${drag.delta}px), 0%))`
    : `translateX(${atOpen ? "0%" : "-100%"})`;

  return (
    <aside
      // z-30: the adjacent content column contains `relative` descendants
      // (SidebarGroup/SidebarMenuItem). Without a positive z-index here the
      // sticky rail (and its absolutely-positioned flyout) would paint beneath
      // those later-in-DOM siblings, bleeding the content through the flyout.
      className="sticky top-0 z-30 flex max-h-screen w-20 flex-col items-center gap-3 border-r bg-sidebar px-2 pb-4"
      style={{ paddingTop: "calc(var(--safe-area-inset-top) + 1rem)" }}
      onTouchStart={handleRailTouchStart}
      onTouchMove={handleRailTouchMove}
      onTouchEnd={handleRailTouchEnd}
    >
      <TooltipProvider delayDuration={200}>
        <Tooltip>
          <TooltipTrigger asChild>
            <Link
              to="/"
              className={cn(
                "flex flex-col items-center rounded-2xl p-1 transition",
                isHomeMode && "bg-primary/10 ring-3 ring-primary/60"
              )}
              aria-label={t("nav:home")}
            >
              <LogoIcon className="h-10 w-10" aria-hidden="true" focusable="false" />
            </Link>
          </TooltipTrigger>
          <TooltipContent side="right" sideOffset={12}>
            <p>{t("nav:home")}</p>
          </TooltipContent>
        </Tooltip>
        <div className="scrollbar-thin flex min-h-0 flex-1 flex-col items-center gap-3 overflow-y-auto border-t py-3">
          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            onDragStart={handleDragStart}
            onDragEnd={handleDragEnd}
            onDragCancel={handleDragCancel}
          >
            <SortableContext
              items={memberGuilds.map((guild) => guild.id)}
              strategy={verticalListSortingStrategy}
            >
              {memberGuilds.map((guild) => (
                <SortableGuildButton
                  key={guild.id}
                  guild={guild}
                  isActive={guild.id === activeGuildId}
                  isHomeMode={isHomeMode}
                  onSelect={handleGuildSwitch}
                />
              ))}
            </SortableContext>
            <DragOverlay>
              {draggedGuild ? (
                <div className="pointer-events-none flex h-12 w-12 items-center justify-center rounded-2xl border-3 border-primary/60 bg-primary/20 opacity-80 shadow-lg">
                  <GuildAvatar
                    name={draggedGuild.name}
                    icon={draggedGuild.icon_base64}
                    active={draggedGuild.id === activeGuildId}
                  />
                </div>
              ) : null}
            </DragOverlay>
          </DndContext>
          {grantGuilds.length > 0 ? (
            <div className="flex flex-col items-center gap-3 border-t pt-3">
              {grantGuilds.map((guild) => (
                <GrantGuildButton
                  key={guild.id}
                  guild={guild}
                  isActive={guild.id === activeGuildId}
                  onSelect={handleGuildSwitch}
                />
              ))}
            </div>
          ) : null}
        </div>
        <div className="flex flex-col items-center gap-2 border-t pt-3">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 rounded-full text-muted-foreground hover:text-foreground"
                onClick={() => setExpanded(true)}
                aria-label={t("guilds:expandGuilds")}
              >
                <ChevronsRight className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="right" sideOffset={12}>
              <p>{t("guilds:guildsHeading")}</p>
            </TooltipContent>
          </Tooltip>
          {canCreateGuilds ? <CreateGuildButton /> : null}
        </div>
      </TooltipProvider>

      {render ? (
        <>
          {/* Desktop click-away. On mobile the panel covers the whole drawer. */}
          <button
            type="button"
            className="fixed inset-0 z-30 hidden cursor-default lg:block"
            onClick={collapse}
            aria-label={t("guilds:collapseGuilds")}
            tabIndex={-1}
          />
          <div
            // Overlay the whole sidebar (rail + content column): stay anchored
            // at the rail's left edge and span the full sidebar width — on
            // mobile the drawer width, on desktop --sidebar-width.
            className="absolute top-0 left-0 z-40 flex h-screen w-[var(--sidebar-width-mobile,90vw)] flex-col border-r bg-sidebar shadow-lg lg:w-[var(--sidebar-width,20rem)]"
            style={{
              transform: panelTransform,
              transition: drag ? "none" : `transform ${FLYOUT_TRANSITION_MS}ms ease-out`,
              paddingTop: "var(--safe-area-inset-top)",
            }}
            onTouchStart={handlePanelTouchStart}
            onTouchMove={handlePanelTouchMove}
            onTouchEnd={handlePanelTouchEnd}
          >
            <div className="flex h-12 shrink-0 items-center justify-between border-b px-4">
              <h2 className="font-semibold text-lg">{t("guilds:guildsHeading")}</h2>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 text-muted-foreground hover:text-foreground"
                onClick={collapse}
                aria-label={t("guilds:collapseGuilds")}
              >
                <ChevronsLeft className="h-4 w-4" />
              </Button>
            </div>
            <div className="scrollbar-thin flex flex-1 flex-col gap-1 overflow-y-auto p-2">
              <DndContext
                sensors={sensors}
                collisionDetection={closestCenter}
                onDragStart={handleDragStart}
                onDragEnd={handleDragEnd}
                onDragCancel={handleDragCancel}
              >
                <SortableContext
                  items={memberGuilds.map((guild) => `${FLYOUT_DRAG_PREFIX}${guild.id}`)}
                  strategy={verticalListSortingStrategy}
                >
                  {memberGuilds.map((guild) => (
                    <SortableGuildRow
                      key={guild.id}
                      guild={guild}
                      isActive={guild.id === activeGuildId}
                      isHomeMode={isHomeMode}
                      onSelect={handleGuildSwitch}
                    />
                  ))}
                </SortableContext>
                <DragOverlay>
                  {draggedGuild ? (
                    <GuildRow
                      guild={draggedGuild}
                      isActive={draggedGuild.id === activeGuildId}
                      isHomeMode={isHomeMode}
                      onSelect={() => {}}
                      style={{ cursor: "grabbing" }}
                    />
                  ) : null}
                </DragOverlay>
              </DndContext>
              {grantGuilds.length > 0 ? (
                <div className="mt-1 flex flex-col gap-1 border-t pt-2">
                  {grantGuilds.map((guild) => (
                    <GuildRow
                      key={guild.id}
                      guild={guild}
                      isActive={guild.id === activeGuildId}
                      isHomeMode={isHomeMode}
                      onSelect={handleGuildSwitch}
                    />
                  ))}
                </div>
              ) : null}
            </div>
            {canCreateGuilds ? (
              <div className="shrink-0 border-t p-2">
                <CreateGuildButton expanded />
              </div>
            ) : null}
          </div>
        </>
      ) : null}
    </aside>
  );
};
