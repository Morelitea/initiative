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

const navItems: NavItem[] = [
  { label: "Projects", to: "/", end: true },
  { label: "My Tasks", to: "/tasks" },
];

export const AppHeader = () => {
  const { user, logout } = useAuth();
  const userDisplayName = user?.full_name ?? user?.email ?? "Initiative member";
  const userEmail = user?.email ?? "";
  const userInitials =
    userDisplayName
      .split(/\s+/)
      .map((part) => part.charAt(0).toUpperCase())
      .join("")
      .slice(0, 2) || "PP";
  const avatarSrc = user?.avatar_url || user?.avatar_base64 || null;
  return (
    <header className="sticky top-0 z-40 border-b bg-card/80 backdrop-blur supports-[backdrop-filter]:bg-card/60">
      <div className="flex h-16 items-center gap-3 px-4 md:px-8">
        <MobileMenu navItems={navItems} user={user} onLogout={logout} />
        <Link
          to="/"
          className="flex items-center gap-3 text-lg font-semibold tracking-tight text-primary"
        >
          <LogoIcon className="h-8 w-8" aria-hidden="true" focusable="false" />
          initiative
        </Link>
        <nav className="hidden items-center gap-4 text-sm font-medium text-muted-foreground md:flex">
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
          {user ? <NotificationBell /> : null}
          <div className="hidden items-center gap-3 md:flex">
            <ModeToggle />
            {user ? (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    className="rounded-full border bg-card p-0.5 transition hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
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
                      <p className="text-sm font-medium leading-none">{userDisplayName}</p>
                      <p className="text-xs text-muted-foreground">{userEmail}</p>
                    </div>
                  </DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem asChild>
                    <Link to="/profile">User Settings</Link>
                  </DropdownMenuItem>
                  {user?.role === "admin" ? (
                    <DropdownMenuItem asChild>
                      <Link to="/settings">Admin Settings</Link>
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
