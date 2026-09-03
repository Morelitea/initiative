import { Link, useLocation } from "@tanstack/react-router";
import {
  CalendarDays,
  ChartColumn,
  LayoutGrid,
  MessageSquare,
  PenLine,
  SquareCheckBig,
  Users,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { usePendingMessageRequests } from "@/hooks/useDirectMessages";
import { useConversations, useUnreadMessages } from "@/hooks/useMyMessages";

export const HomeSidebarContent = () => {
  const { t } = useTranslation("nav");
  const location = useLocation();
  // Two things put a mark on My Messages, and they mean the same thing to the
  // person seeing it: something is there that you have not dealt with. One is
  // somebody asking to message you; the other is a message you have not read.
  const pendingRequests = usePendingMessageRequests();
  const conversations = useConversations();
  const unread = useUnreadMessages((conversations.data?.conversations ?? []).map((row) => row.id));
  const unreadTotal = [...(unread.data?.values() ?? [])].reduce((total, count) => total + count, 0);

  const navItems = [
    { to: "/", label: t("myTasks"), icon: SquareCheckBig, exact: true },
    { to: "/created-tasks", label: t("tasksICreated"), icon: PenLine },
    { to: "/my-calendar", label: t("myCalendar"), icon: CalendarDays },
    { to: "/my-tools", label: t("myTools"), icon: LayoutGrid },
    { to: "/contacts", label: t("myContacts"), icon: Users },
    {
      to: "/messages",
      label: t("myMessages"),
      icon: MessageSquare,
      waiting: pendingRequests + unreadTotal,
    },
    { to: "/user-stats", label: t("myStats"), icon: ChartColumn },
  ];

  return (
    <>
      <SidebarHeader
        className="gap-0 border-b p-0"
        style={{ paddingTop: "var(--safe-area-inset-top)" }}
      >
        <div className="flex h-12 min-w-0 items-center justify-between gap-2 px-2.5">
          <h2 className="pride-wordmark min-w-0 flex-1 truncate font-semibold text-lg">
            initiative
          </h2>
        </div>
      </SidebarHeader>
      <SidebarContent className="h-full overflow-y-auto overflow-x-hidden">
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {navItems.map((item) => {
                const isActive = item.exact
                  ? location.pathname === item.to
                  : location.pathname.startsWith(item.to);
                return (
                  <SidebarMenuItem key={item.to}>
                    <SidebarMenuButton asChild isActive={isActive}>
                      <Link to={item.to} className="flex items-center gap-2">
                        <item.icon className="h-4 w-4" />
                        <span>{item.label}</span>
                        {/* A dot carries no text, so the count it stands for
                            is written out for anyone not looking at it. */}
                        {item.waiting ? (
                          <span className="ms-auto flex shrink-0 items-center">
                            <span className="sr-only">
                              {t("requestsWaiting", { count: item.waiting })}
                            </span>
                            <span
                              aria-hidden="true"
                              className="size-2 rounded-full bg-destructive"
                            />
                          </span>
                        ) : null}
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
    </>
  );
};
