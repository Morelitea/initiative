import { Menu } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";

import { cn } from "@/lib/utils";
import type { User } from "@/types/api";
import { ModeToggle } from "@/components/ModeToggle";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";

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
  const location = useLocation();

  const userDisplayName = user?.full_name ?? user?.email ?? "Initiative member";
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
              Navigation
            </SheetTitle>
            <SheetDescription className="sr-only">Mobile navigation drawer</SheetDescription>
          </SheetHeader>
          <div className="flex items-start justify-between gap-4">
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
            <div className="shrink-0">
              <ModeToggle />
            </div>
          </div>
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
            <Link
              to="/profile"
              onClick={() => setIsOpen(false)}
              className="block rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground"
            >
              User settings
            </Link>
            {user?.role === "admin" ? (
              <Link
                to="/settings"
                onClick={() => setIsOpen(false)}
                className="block rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground"
              >
                Admin settings
              </Link>
            ) : null}
            <Button type="button" variant="secondary" className="w-full" onClick={handleLogout}>
              Sign out
            </Button>
          </div>
        </SheetContent>
      </Sheet>
    </div>
  );
};
