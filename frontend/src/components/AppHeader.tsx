import { Link, NavLink } from "react-router-dom";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { MobileMenu, type NavItem } from "@/components/MobileMenu";
import { ModeToggle } from "@/components/ModeToggle";
import { LogoIcon } from "@/components/LogoIcon";
import { NotificationBell } from "@/components/notifications/NotificationBell";
import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";
import { useRoleLabels, getRoleLabel } from "@/hooks/useRoleLabels";

const navItems: NavItem[] = [
  { label: "Projects", to: "/", end: true },
  { label: "My Tasks", to: "/tasks" },
  { label: "Documents", to: "/documents" },
];

export const AppHeader = () => {
  const { user, logout } = useAuth();
  const { activeGuild } = useGuilds();
  const { data: roleLabels } = useRoleLabels();
  const memberLabel = getRoleLabel("member", roleLabels);
  const userDisplayName = user?.full_name ?? user?.email ?? memberLabel;
  const userEmail = user?.email ?? "";
  const userInitials =
    userDisplayName
      .split(/\s+/)
      .map((part) => part.charAt(0).toUpperCase())
      .join("")
      .slice(0, 2) || "PP";
  const avatarSrc = user?.avatar_url || user?.avatar_base64 || null;
  const isGuildAdmin = user?.role === "admin" || activeGuild?.role === "admin";
  const isSuperUser = user?.id === 1;

  return (
    <header className="bg-card/80 supports-backdrop-filter:bg-card/60 sticky top-0 z-50 border-b backdrop-blur">
      <div className="flex h-16 items-center gap-3 px-4 md:px-8">
        <MobileMenu navItems={navItems} user={user} onLogout={logout} />
        <Link
          to="/"
          className="text-primary flex items-center gap-3 text-lg font-semibold tracking-tight"
        >
          <LogoIcon className="h-8 w-8" aria-hidden="true" focusable="false" />
          initiative
        </Link>
        <nav className="text-muted-foreground hidden items-center gap-4 text-sm font-medium md:flex">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => (isActive ? "text-foreground" : undefined)}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-3">
          {activeGuild ? (
            <div className="border-muted bg-muted/60 text-muted-foreground hidden rounded-full border px-3 py-1 text-xs font-medium md:flex">
              {activeGuild.name}
            </div>
          ) : null}
          {user ? <NotificationBell /> : null}
          <div className="hidden items-center gap-3 md:flex">
            <ModeToggle />
            {user ? (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    className="bg-card hover:bg-muted focus-visible:ring-ring rounded-full border p-0.5 transition focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none"
                    aria-label="Account menu"
                  >
                    <Avatar>
                      {avatarSrc ? <AvatarImage src={avatarSrc} alt={userDisplayName} /> : null}
                      <AvatarFallback>{userInitials}</AvatarFallback>
                    </Avatar>
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-56">
                  <DropdownMenuLabel className="font-normal">
                    <div className="flex flex-col space-y-1">
                      <p className="text-sm leading-none font-medium">{userDisplayName}</p>
                      <p className="text-muted-foreground text-xs">{userEmail}</p>
                    </div>
                  </DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem asChild>
                    <Link to="/profile">User Settings</Link>
                  </DropdownMenuItem>
                  {isGuildAdmin ? (
                    <DropdownMenuItem asChild>
                      <Link to="/settings/guild">Guild Settings</Link>
                    </DropdownMenuItem>
                  ) : null}
                  {isSuperUser ? (
                    <DropdownMenuItem asChild>
                      <Link to="/settings/admin">Platform Settings</Link>
                    </DropdownMenuItem>
                  ) : null}
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onSelect={() => logout()}>Sign out</DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            ) : null}
          </div>
        </div>
      </div>
    </header>
  );
};
