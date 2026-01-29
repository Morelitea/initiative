import { useCallback, useMemo, useState } from "react";
import type { CSSProperties, FormEvent } from "react";
import { useNavigate, useLocation, Link } from "react-router-dom";
import { Plus } from "lucide-react";
import {
  DndContext,
  DragEndEvent,
  DragOverlay,
  DragStartEvent,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

import { useGuilds } from "@/hooks/useGuilds";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import {
  Dialog,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import type { Guild } from "@/types/api";
import { LogoIcon } from "../LogoIcon";
import { GuildContextMenu } from "./GuildContextMenu";

const CreateGuildButton = () => {
  const { createGuild, canCreateGuilds, switchGuild } = useGuilds();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

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
      const message = err instanceof Error ? err.message : "Unable to create guild";
      setError(message);
      toast.error(message);
    } finally {
      setSubmitting(false);
      navigate("/");
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
              className="border-muted-foreground/40 text-muted-foreground hover:bg-muted h-12 w-12 rounded-2xl border border-dashed bg-transparent"
              aria-label="Create guild"
            >
              <Plus className="h-5 w-5" />
            </Button>
          </DialogTrigger>
        </TooltipTrigger>
        <TooltipContent side="right" sideOffset={12}>
          <p>Create Guild</p>
        </TooltipContent>
      </Tooltip>
      <DialogContent className="bg-card max-h-screen overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Create a new guild</DialogTitle>
          <DialogDescription>
            Guilds group initiatives and projects. You can invite teammates after creation.
          </DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="space-y-2">
            <Label htmlFor="guild-name">Guild name</Label>
            <Input
              id="guild-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Product Engineering"
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="guild-description">Description</Label>
            <Textarea
              id="guild-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="Optional summary"
              rows={3}
            />
          </div>
          {error ? <p className="text-destructive text-sm">{error}</p> : null}
          <DialogFooter>
            <Button type="submit" disabled={submitting}>
              {submitting ? "Creating…" : "Create guild"}
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
  const initials = useMemo(() => {
    const parts = name.trim().split(/\s+/);
    if (!parts.length) {
      return "G";
    }
    return parts
      .slice(0, 2)
      .map((part) => part.charAt(0).toUpperCase())
      .join("");
  }, [name]);
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
  onSelect,
}: {
  guild: Guild;
  isActive: boolean;
  onSelect: (guildId: number) => void;
}) => {
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
              "focus-visible:ring-ring flex h-12 w-12 cursor-grab items-center justify-center rounded-2xl border-3 transition focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none active:cursor-grabbing",
              isActive
                ? "border-primary/60 bg-primary/10 text-primary"
                : "bg-muted text-muted-foreground hover:bg-muted/80 border-transparent"
            )}
            aria-label={`Switch to ${guild.name}`}
            style={style}
            {...attributes}
            {...listeners}
          >
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

export const GuildSidebar = () => {
  const { guilds, activeGuildId, switchGuild, reorderGuilds, canCreateGuilds } = useGuilds();
  const navigate = useNavigate();
  const location = useLocation();
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

  const handleGuildSwitch = async (guildId: number) => {
    if (guildId === activeGuildId) return;

    // Determine where to go based on current page
    const currentPath = location.pathname;
    let targetPath = "/"; // Default to My Tasks
    if (currentPath.startsWith("/projects")) {
      // Projects are guild-scoped, so return to the list.
      targetPath = "/projects";
    } else if (currentPath.startsWith("/initiatives")) {
      // Initiative detail IDs are guild-scoped, so return to the list.
      targetPath = "/initiatives";
    } else if (currentPath.startsWith("/documents")) {
      // If we are on a document detail page (/documents/123), that ID won't exist in the new guild.
      // So we fallback to the Document List page (/documents).
      targetPath = "/documents";
    } else if (currentPath.startsWith("/settings")) {
      // Settings pages are generally safe to persist
      targetPath = currentPath;
    } else if (currentPath.startsWith("/profile")) {
      // User profile is global
      targetPath = currentPath;
    }

    await switchGuild(guildId);

    if (targetPath !== "/") {
      // My tasks is global, don't navigate/refresh
      navigate(targetPath);
    }
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
      const oldIndex = guilds.findIndex((guild) => guild.id === activeId);
      const newIndex = guilds.findIndex((guild) => guild.id === overId);
      if (oldIndex === -1 || newIndex === -1) {
        return;
      }
      const orderedIds = arrayMove(guilds, oldIndex, newIndex).map((guild) => guild.id);
      reorderGuilds(orderedIds);
    },
    [guilds, reorderGuilds]
  );

  const handleDragCancel = useCallback(() => {
    setActiveDragId(null);
  }, []);

  return (
    <aside className="bg-sidebar sticky top-0 flex max-h-screen w-20 flex-col items-center gap-3 border-r px-2 py-4">
      <TooltipProvider delayDuration={200}>
        <Tooltip>
          <TooltipTrigger asChild>
            <Link to="/" className="flex flex-col items-center">
              <LogoIcon className="h-12 w-12" aria-hidden="true" focusable="false" />
              <span className="text-primary text-s text-center">initiative</span>
            </Link>
          </TooltipTrigger>
          <TooltipContent side="right" sideOffset={12}>
            <p>My Tasks</p>
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
              items={guilds.map((guild) => guild.id)}
              strategy={verticalListSortingStrategy}
            >
              {guilds.map((guild) => (
                <SortableGuildButton
                  key={guild.id}
                  guild={guild}
                  isActive={guild.id === activeGuildId}
                  onSelect={handleGuildSwitch}
                />
              ))}
            </SortableContext>
            <DragOverlay>
              {draggedGuild ? (
                <div className="border-primary/60 bg-primary/20 pointer-events-none flex h-12 w-12 items-center justify-center rounded-2xl border-3 opacity-80 shadow-lg">
                  <GuildAvatar
                    name={draggedGuild.name}
                    icon={draggedGuild.icon_base64}
                    active={draggedGuild.id === activeGuildId}
                  />
                </div>
              ) : null}
            </DragOverlay>
          </DndContext>
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
