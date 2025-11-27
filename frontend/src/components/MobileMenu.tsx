import { Menu } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import type { User } from "@/types/api";
import { ModeToggle } from "@/components/ModeToggle";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useRoleLabels, getRoleLabel } from "@/hooks/useRoleLabels";
import { useGuilds } from "@/hooks/useGuilds";
import { Textarea } from "@/components/ui/textarea";
import { GuildAvatar } from "./guilds/GuildSidebar";

export interface NavItem {
  label: string;
  to: string;
  end?: boolean;
}

interface MobileMenuProps {
  navItems: NavItem[];
  user: User | null;
  onLogout: () => void;
}

export const MobileMenu = ({ navItems, user, onLogout }: MobileMenuProps) => {
  const [isOpen, setIsOpen] = useState(false);
  const [isCreateGuildOpen, setIsCreateGuildOpen] = useState(false);
  const [newGuildName, setNewGuildName] = useState("");
  const [newGuildDescription, setNewGuildDescription] = useState("");
  const [creatingGuild, setCreatingGuild] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const location = useLocation();
  const {
    guilds,
    activeGuild,
    activeGuildId,
    switchGuild: switchGuildFn,
    createGuild,
  } = useGuilds();
  const { data: roleLabels } = useRoleLabels();
  const adminLabel = getRoleLabel("admin", roleLabels);
  const memberLabel = getRoleLabel("member", roleLabels);
  const isSuperUser = user?.id === 1;
  const userDisplayName = user?.full_name ?? user?.email ?? memberLabel;
  const userEmail = user?.email ?? "";
  const avatarSrc = user?.avatar_url || user?.avatar_base64 || undefined;
  const userInitials =
    userDisplayName
      .split(/\s+/)
      .map((part) => part.charAt(0).toUpperCase())
      .join("")
      .slice(0, 2) || "PP";

  useEffect(() => {
    setIsOpen(false);
  }, [location.pathname]);

  const handleLogout = () => {
    onLogout();
    setIsOpen(false);
  };

  const handleGuildChange = async (value: string) => {
    if (value === "create") {
      setIsCreateGuildOpen(true);
      return;
    }
    const guildId = Number(value);
    if (!Number.isFinite(guildId) || guildId === activeGuildId) {
      return;
    }
    await switchGuildFn(guildId);
    setIsOpen(false);
  };

  const handleCreateGuildSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setCreatingGuild(true);
    setCreateError(null);
    try {
      await createGuild({ name: newGuildName, description: newGuildDescription });
      setIsCreateGuildOpen(false);
      setNewGuildName("");
      setNewGuildDescription("");
      setIsOpen(false);
    } catch (error) {
      console.error(error);
      const message =
        error instanceof Error ? error.message : "Unable to create guild. Please try again.";
      setCreateError(message);
      toast.error(message);
    } finally {
      setCreatingGuild(false);
    }
  };

  return (
    <div className="md:hidden">
      <Sheet open={isOpen} onOpenChange={setIsOpen}>
        <SheetTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="Open navigation menu"
            aria-haspopup="dialog"
            aria-expanded={isOpen}
          >
            <Menu className="h-5 w-5" aria-hidden="true" />
          </Button>
        </SheetTrigger>
        <SheetContent
          side="left"
          className="flex h-full w-80 max-w-[85vw] flex-col gap-4 border-r bg-card p-6"
        >
          <SheetHeader className="items-start text-left">
            <SheetTitle className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              <div className="mt-2 flex items-center justify-between gap-4">
                {activeGuild && (
                  <GuildAvatar
                    name={activeGuild.name}
                    icon={activeGuild.icon_base64}
                    active={activeGuild.is_active}
                  />
                )}
                <div className="mt-2">
                  <Select
                    value={activeGuildId ? String(activeGuildId) : undefined}
                    onValueChange={handleGuildChange}
                  >
                    <SelectTrigger className="w-48">
                      <SelectValue placeholder="Select guild" />
                    </SelectTrigger>
                    <SelectContent>
                      {guilds.map((guild) => (
                        <SelectItem key={guild.id} value={String(guild.id)}>
                          {guild.name}
                        </SelectItem>
                      ))}
                      <SelectSeparator />
                      <SelectItem value="create" className="text-primary">
                        + Create new guild
                      </SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
            </SheetTitle>
            <SheetDescription className="sr-only">Mobile navigation drawer</SheetDescription>
          </SheetHeader>
          {/* <div className="flex items-start justify-between gap-4">
            <div className="flex items-center gap-3">
              <Avatar className="h-12 w-12">
                {avatarSrc ? <AvatarImage src={avatarSrc} alt={userDisplayName} /> : null}
                <AvatarFallback>{userInitials}</AvatarFallback>
              </Avatar>
              <div>
                <p className="text-base font-semibold leading-tight text-foreground">
                  {userDisplayName}
                </p>
                {userEmail ? <p className="text-sm text-muted-foreground">{userEmail}</p> : null}
              </div>
            </div>
          </div> */}
          <nav className="flex flex-col gap-1">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  cn(
                    "rounded-md px-3 py-2 text-base font-medium transition-colors",
                    isActive
                      ? "bg-muted text-foreground"
                      : "text-muted-foreground hover:bg-muted/70 hover:text-foreground"
                  )
                }
                onClick={() => setIsOpen(false)}
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="mt-auto space-y-2 border-t border-border pt-4">
            <div className="flex items-center gap-3">
              <Avatar className="h-12 w-12">
                {avatarSrc ? <AvatarImage src={avatarSrc} alt={userDisplayName} /> : null}
                <AvatarFallback>{userInitials}</AvatarFallback>
              </Avatar>
              <div>
                <p className="text-base font-semibold leading-tight text-foreground">
                  {userDisplayName}
                </p>
                {userEmail ? <p className="text-sm text-muted-foreground">{userEmail}</p> : null}
              </div>

              <div className="shrink-0">
                <ModeToggle />
              </div>
            </div>
            <Link
              to="/profile"
              onClick={() => setIsOpen(false)}
              className="block rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground"
            >
              User settings
            </Link>
            {user?.role === "admin" ? (
              <Link
                to="/settings/guild"
                onClick={() => setIsOpen(false)}
                className="block rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground"
              >
                Guild settings
              </Link>
            ) : null}
            {isSuperUser ? (
              <Link
                to="/settings/admin"
                onClick={() => setIsOpen(false)}
                className="block rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground"
              >
                {adminLabel} settings
              </Link>
            ) : null}
            <Button type="button" variant="secondary" className="w-full" onClick={handleLogout}>
              Sign out
            </Button>
          </div>
        </SheetContent>
      </Sheet>
      <Dialog
        open={isCreateGuildOpen}
        onOpenChange={(next) => !creatingGuild && setIsCreateGuildOpen(next)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create a new guild</DialogTitle>
            <DialogDescription>
              Guilds group initiatives and projects. Invite teammates once it is created.
            </DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={handleCreateGuildSubmit}>
            <div className="space-y-2">
              <Label htmlFor="mobile-guild-name">Guild name</Label>
              <Input
                id="mobile-guild-name"
                value={newGuildName}
                onChange={(event) => setNewGuildName(event.target.value)}
                placeholder="Product Engineering"
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="mobile-guild-description">Description</Label>
              <Textarea
                id="mobile-guild-description"
                value={newGuildDescription}
                onChange={(event) => setNewGuildDescription(event.target.value)}
                placeholder="Optional summary"
                rows={3}
              />
            </div>
            {createError ? <p className="text-sm text-destructive">{createError}</p> : null}
            <DialogFooter>
              <Button type="submit" disabled={creatingGuild}>
                {creatingGuild ? "Creating…" : "Create guild"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
};
