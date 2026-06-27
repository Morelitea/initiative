import { useNavigate } from "@tanstack/react-router";
import { FilePlus, Home, Menu, Plus, Search, SquareCheckBig } from "lucide-react";
import { useTranslation } from "react-i18next";

import { getOpenCommandCenter } from "@/components/CommandCenter";
import { getOpenCreateDocumentWizard } from "@/components/documents/CreateDocumentWizard";
import { usePrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import { getOpenCreateTaskWizard } from "@/components/tasks/CreateTaskWizard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useSidebar } from "@/components/ui/sidebar";
import { useIsMobile } from "@/hooks/use-mobile";
import { useAuth } from "@/hooks/useAuth";
import { useNotifications } from "@/hooks/useNotifications";

const pillClass =
  "pointer-events-auto flex items-center gap-1 rounded-full border bg-card/90 p-1 shadow-lg backdrop-blur supports-backdrop-filter:bg-card/70";

/**
 * App-wide floating bottom navigation. The hamburger/search/home pill is mobile
 * only; the route-aware add pill renders at every viewport size and replaces the
 * old per-page `fixed right-6 bottom-6` floating add buttons.
 */
export function BottomNav() {
  const { t } = useTranslation("nav");
  const isMobile = useIsMobile();
  const navigate = useNavigate();
  const { setOpenMobile } = useSidebar();
  const { user } = useAuth();
  const { isCreateContext, action } = usePrimaryCreateAction();

  const notificationsQuery = useNotifications({
    refetchInterval: 30_000,
    enabled: Boolean(user) && isMobile,
  });
  const unreadCount = notificationsQuery.data?.unread_count ?? 0;

  // Hide the add button entirely on a create-context route where the user lacks
  // permission. Non-create routes (no registration) fall back to the global menu.
  const hideAdd = isCreateContext && action === null;

  return (
    <div
      className="pointer-events-none fixed inset-x-0 bottom-0 z-40"
      style={{ paddingBottom: "var(--safe-area-inset-bottom)" }}
    >
      <div className="flex w-full items-end gap-3 px-4 pb-4 sm:px-6 sm:pb-6">
        {isMobile && (
          <nav className={pillClass} aria-label={t("bottomNav.label")}>
            <Button
              variant="ghost"
              size="icon"
              className="relative h-11 w-11 rounded-full"
              onClick={() => setOpenMobile(true)}
              aria-label={t("bottomNav.menu")}
            >
              <Menu className="h-5 w-5" />
              {unreadCount > 0 ? (
                <Badge className="absolute -top-0.5 -right-0.5 h-5 min-w-5 justify-center rounded-full px-1 py-0 text-[11px]">
                  {unreadCount > 99 ? "99+" : unreadCount}
                </Badge>
              ) : null}
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-11 w-11 rounded-full"
              onClick={() => getOpenCommandCenter()?.()}
              aria-label={t("bottomNav.search")}
            >
              <Search className="h-5 w-5" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-11 w-11 rounded-full"
              onClick={() => void navigate({ to: "/" })}
              aria-label={t("bottomNav.home")}
            >
              <Home className="h-5 w-5" />
            </Button>
          </nav>
        )}

        {!hideAdd &&
          (action ? (
            <Button
              size="icon"
              className="pointer-events-auto ml-auto h-12 w-12 rounded-full shadow-lg shadow-primary/40"
              onClick={() => action.run()}
              aria-label={t("bottomNav.add")}
            >
              <Plus className="h-5 w-5" />
            </Button>
          ) : (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  size="icon"
                  className="pointer-events-auto ml-auto h-12 w-12 rounded-full shadow-lg shadow-primary/40"
                  aria-label={t("bottomNav.add")}
                >
                  <Plus className="h-5 w-5" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" side="top" className="mb-2">
                <DropdownMenuItem onSelect={() => getOpenCreateTaskWizard()?.()}>
                  <SquareCheckBig className="mr-2 h-4 w-4" />
                  {t("bottomNav.addTask")}
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => getOpenCreateDocumentWizard()?.()}>
                  <FilePlus className="mr-2 h-4 w-4" />
                  {t("bottomNav.addDocument")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ))}
      </div>
    </div>
  );
}
