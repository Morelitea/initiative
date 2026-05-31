import {
  closestCenter,
  DndContext,
  type DragEndEvent,
  DragOverlay,
  type DragStartEvent,
  KeyboardSensor,
  PointerSensor,
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
import { Clock, Plus } from "lucide-react";
import type { CSSProperties, FormEvent } from "react";
import { useCallback, useMemo, useState } from "react";
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

const CreateGuildButton = () => {
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

  return (
    <Dialog open={open} onOpenChange={(next) => !submitting && setOpen(next)}>
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
                className="-translate-x-1/2 absolute -bottom-2 left-1/2 z-10 mt-1 h-1 w-7 rounded-full bg-primary/60"
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

export const GuildSidebar = ({ isHomeMode = false }: { isHomeMode?: boolean }) => {
  const { guilds, activeGuildId, switchGuild, reorderGuilds, canCreateGuilds } = useGuilds();
  const { t } = useTranslation(["guilds", "nav"]);
  const router = useRouter();
  const [activeDragId, setActiveDragId] = useState<number | null>(null);
  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 6,
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

  const handleGuildSwitch = (guildId: number) => {
    // Always navigate to the guild dashboard
    if (guildId !== activeGuildId) {
      void switchGuild(guildId);
    }
    router.navigate({ to: guildPath(guildId, "/") });
  };

  const handleDragStart = useCallback((event: DragStartEvent) => {
    const draggedId = Number(event.active.id);
    if (Number.isFinite(draggedId)) {
      setActiveDragId(draggedId);
    }
  }, []);

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event;
      setActiveDragId(null);
      if (!over || active.id === over.id) {
        return;
      }
      const activeId = Number(active.id);
      const overId = Number(over.id);
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
    [memberGuilds, reorderGuilds]
  );

  const handleDragCancel = useCallback(() => {
    setActiveDragId(null);
  }, []);

  return (
    <aside
      className="sticky top-0 flex max-h-screen w-20 flex-col items-center gap-3 border-r bg-sidebar px-2 pb-4"
      style={{ paddingTop: "calc(var(--safe-area-inset-top) + 1rem)" }}
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
        <div className="flex flex-col items-center gap-3 overflow-y-auto border-t pt-3">
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
        {canCreateGuilds ? (
          <div className="flex flex-col items-center gap-2 border-t pt-3">
            <CreateGuildButton />
          </div>
        ) : null}
      </TooltipProvider>
    </aside>
  );
};
