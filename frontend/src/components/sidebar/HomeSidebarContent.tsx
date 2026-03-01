import { Link, useLocation } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { ChartColumn, ListTodo, PenLine, ScrollText, SquareCheckBig } from "lucide-react";

import {
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";

export const HomeSidebarContent = () => {
  const { t } = useTranslation("nav");
  const location = useLocation();

  const navItems = [
    { to: "/", label: t("myTasks"), icon: SquareCheckBig, exact: true },
    { to: "/created-tasks", label: t("tasksICreated"), icon: PenLine },
    { to: "/my-projects", label: t("myProjects"), icon: ListTodo },
    { to: "/my-documents", label: t("myDocuments"), icon: ScrollText },
    { to: "/user-stats", label: t("myStats"), icon: ChartColumn },
  ];

  return (
    <>
      <SidebarHeader className="border-b">
        <div className="flex min-w-0 items-center gap-2 p-4">
          {/* eslint-disable-next-line i18next/no-literal-string */}
          <h2 className="text-center text-lg font-semibold">initiative</h2>
        </div>
      </SidebarHeader>
      <SidebarContent className="h-full overflow-x-hidden overflow-y-auto">
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
