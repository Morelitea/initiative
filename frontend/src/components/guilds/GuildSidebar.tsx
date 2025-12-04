import { useMemo, useState, FormEvent } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { Plus } from "lucide-react";

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

const CreateGuildButton = () => {
  const { createGuild, canCreateGuilds } = useGuilds();
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
      await createGuild({ name, description });
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

export const GuildSidebar = () => {
  const { guilds, activeGuildId, switchGuild, canCreateGuilds } = useGuilds();
  const navigate = useNavigate();
  const location = useLocation();

  const handleGuildSwitch = async (guildId: number) => {
    if (guildId === activeGuildId) return;

    // Determine where to go based on current page
    const currentPath = location.pathname;
    let targetPath = "/"; // Default to Project Dashboard
    if (currentPath.startsWith("/tasks")) {
      // My Tasks is safe to persist across guilds
      targetPath = "/tasks";
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

    navigate(targetPath);
  };

  return (
    <aside className="bg-card/80 sticky top-0 hidden max-h-screen w-20 flex-col items-center gap-3 border-r px-2 py-4 sm:flex">
      <span className="text-muted-foreground text-center text-xs">Guilds</span>
      <div className="flex flex-1 flex-col items-center gap-3 overflow-y-auto">
        <TooltipProvider delayDuration={200}>
          {guilds.map((guild) => {
            const isActive = guild.id === activeGuildId;
            return (
              <Tooltip key={guild.id}>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    onClick={() => handleGuildSwitch(guild.id)}
                    className={`focus-visible:ring-ring flex h-12 w-12 items-center justify-center rounded-2xl border-3 transition focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none ${
                      isActive
                        ? "border-primary/60 bg-primary/10 text-primary"
                        : "bg-muted text-muted-foreground hover:bg-muted/80 border-transparent"
                    }`}
                    aria-label={`Switch to ${guild.name}`}
                  >
                    <GuildAvatar name={guild.name} icon={guild.icon_base64} active={isActive} />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="right" sideOffset={12}>
                  {guild.name}
                </TooltipContent>
              </Tooltip>
            );
          })}
        </TooltipProvider>
      </div>
      {canCreateGuilds ? (
        <div className="border-border flex flex-col items-center gap-2 border-t pt-2">
          <span className="text-muted-foreground text-center text-xs">Create Guild</span>
          <CreateGuildButton />
        </div>
      ) : null}
    </aside>
  );
};
