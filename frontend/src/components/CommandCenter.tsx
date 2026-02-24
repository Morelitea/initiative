import { useEffect, useMemo, useState } from "react";
import { useRouter } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import {
  CheckSquare,
  ListTodo,
  PenLine,
  ScrollText,
  Users,
  Settings,
  BarChart3,
  UserCog,
} from "lucide-react";

import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { commandFilter } from "@/lib/fuzzyMatch";
import { getDocumentIcon, getDocumentIconColor } from "@/lib/fileUtils";
import { guildPath, useGuildPath } from "@/lib/guildUrl";
import { useRecentProjects, useProjects } from "@/hooks/useProjects";
import { useAllDocumentIds } from "@/hooks/useDocuments";
import { useTasks } from "@/hooks/useTasks";
import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";
import type { ProjectRead } from "@/api/generated/initiativeAPI.schemas";

// Module-level callback so other components can open the command center
let openCommandCenter: (() => void) | null = null;
export function getOpenCommandCenter() {
  return openCommandCenter;
}

export function CommandCenter() {
  const [open, setOpen] = useState(false);
  const { t } = useTranslation("command");
  const router = useRouter();
  const { user } = useAuth();
  const { activeGuild, activeGuildId } = useGuilds();
  const getGuildPath = useGuildPath();

  // Expose open callback for external triggers (e.g. sidebar button)
  useEffect(() => {
    openCommandCenter = () => setOpen(true);
    return () => {
      openCommandCenter = null;
    };
  }, []);

  // Keyboard shortcut
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, []);

  // 3-finger tap to open on mobile/touch devices
  useEffect(() => {
    const handleTouchStart = (e: TouchEvent) => {
      if (e.touches.length === 3) {
        setOpen(true);
      }
    };
    document.addEventListener("touchstart", handleTouchStart);
    return () => document.removeEventListener("touchstart", handleTouchStart);
  }, []);

  // Data hooks — all use existing cached data except tasks which fetches when dialog opens
  const recentQuery = useRecentProjects({ staleTime: 30_000 });
  const projectsQuery = useProjects(undefined, { staleTime: 60_000 });
  const documentsQuery = useAllDocumentIds({ staleTime: 60_000 });
  const tasksQuery = useTasks(
    {
      page_size: 50,
      conditions: user ? [{ field: "assignee_ids", op: "in_" as const, value: [user.id] }] : [],
    },
    { enabled: open && !!user, staleTime: 30_000 }
  );

  const recentProjects = (recentQuery.data as ProjectRead[] | undefined) ?? [];
  const projects = projectsQuery.data?.items ?? [];
  const documents = documentsQuery.data ?? [];
  const tasks = tasksQuery.data?.items ?? [];

  const isGuildAdmin = activeGuild?.role === "admin";
  const isPlatformAdmin = user?.role === "admin";

  // Static pages
  const pages = useMemo(() => {
    const items = [
      { label: t("pages.myTasks"), path: "/", icon: CheckSquare },
      { label: t("pages.tasksICreated"), path: "/created-tasks", icon: PenLine },
      { label: t("pages.myProjects"), path: "/my-projects", icon: ListTodo },
      { label: t("pages.myDocuments"), path: "/my-documents", icon: ScrollText },
      { label: t("pages.myStats"), path: "/user-stats", icon: BarChart3 },
      { label: t("pages.userSettings"), path: "/profile", icon: UserCog },
      {
        label: t("pages.allProjects"),
        path: getGuildPath("/projects"),
        icon: ListTodo,
      },
      {
        label: t("pages.allDocuments"),
        path: getGuildPath("/documents"),
        icon: ScrollText,
      },
      {
        label: t("pages.allInitiatives"),
        path: getGuildPath("/initiatives"),
        icon: Users,
      },
    ];

    if (isGuildAdmin) {
      items.push({
        label: t("pages.guildSettings"),
        path: "/settings/guild",
        icon: Settings,
      });
    }

    if (isPlatformAdmin) {
      items.push({
        label: t("pages.platformSettings"),
        path: "/settings/admin",
        icon: Settings,
      });
    }

    return items;
  }, [t, getGuildPath, isGuildAdmin, isPlatformAdmin]);

  const handleSelect = (path: string) => {
    setOpen(false);
    void router.navigate({ to: path });
  };

  return (
    <CommandDialog open={open} onOpenChange={setOpen} filter={commandFilter}>
      <CommandInput placeholder={t("placeholder")} />
      <CommandList>
        <CommandEmpty>{t("noResults")}</CommandEmpty>

        {/* Suggested — only when not searching (cmdk hides empty groups automatically) */}
        {recentProjects.length > 0 && (
          <CommandGroup heading={t("groups.suggested")}>
            {recentProjects.slice(0, 5).map((project) => (
              <CommandItem
                key={`suggested-${project.id}`}
                value={`suggested-${project.id}-${project.name}`}
                keywords={[project.description ?? "", project.initiative?.name ?? ""]}
                onSelect={() =>
                  handleSelect(
                    activeGuildId
                      ? guildPath(activeGuildId, `/projects/${project.id}`)
                      : `/projects/${project.id}`
                  )
                }
              >
                {project.icon ? (
                  <span className="text-base leading-none">{project.icon}</span>
                ) : (
                  <ListTodo className="text-muted-foreground" />
                )}
                <span>{project.name}</span>
              </CommandItem>
            ))}
          </CommandGroup>
        )}

        {/* Pages */}
        <CommandGroup heading={t("groups.pages")}>
          {pages.map((page) => (
            <CommandItem
              key={`page-${page.path}`}
              value={`page-${page.label}`}
              onSelect={() => handleSelect(page.path)}
            >
              <page.icon className="text-muted-foreground" />
              <span>{page.label}</span>
            </CommandItem>
          ))}
        </CommandGroup>

        {/* Projects */}
        <CommandGroup heading={t("groups.projects")}>
          {projects.map((project) => (
            <CommandItem
              key={`project-${project.id}`}
              value={`project-${project.id}-${project.name}`}
              keywords={[
                project.description ?? "",
                project.initiative?.name ?? "",
                ...(project.tags?.map((tag) => tag.name) ?? []),
              ]}
              onSelect={() =>
                handleSelect(
                  activeGuildId
                    ? guildPath(activeGuildId, `/projects/${project.id}`)
                    : `/projects/${project.id}`
                )
              }
            >
              {project.icon ? (
                <span className="text-base leading-none">{project.icon}</span>
              ) : (
                <ListTodo className="text-muted-foreground" />
              )}
              <span>{project.name}</span>
            </CommandItem>
          ))}
        </CommandGroup>

        {/* Documents */}
        <CommandGroup heading={t("groups.documents")}>
          {documents.map((doc) => {
            const DocIcon = getDocumentIcon(doc.document_type, doc.file_content_type, doc.original_filename);
            const docIconColor = getDocumentIconColor(doc.document_type, doc.file_content_type, doc.original_filename);
            return (
              <CommandItem
                key={`document-${doc.id}`}
                value={`document-${doc.id}-${doc.title}`}
                keywords={[doc.initiative?.name ?? "", ...(doc.tags?.map((tag) => tag.name) ?? [])]}
                onSelect={() =>
                  handleSelect(
                    activeGuildId
                      ? guildPath(activeGuildId, `/documents/${doc.id}`)
                      : `/documents/${doc.id}`
                  )
                }
              >
                <DocIcon className={docIconColor} />
                <span>{doc.title}</span>
              </CommandItem>
            );
          })}
        </CommandGroup>

        {/* Tasks */}
        <CommandGroup heading={t("groups.tasks")}>
          {tasks.map((task) => (
            <CommandItem
              key={`task-${task.id}`}
              value={`task-${task.id}-${task.title}`}
              keywords={[
                task.description ?? "",
                task.project_name ?? "",
                task.initiative_name ?? "",
                ...(task.tags?.map((tag) => tag.name) ?? []),
              ]}
              onSelect={() =>
                handleSelect(
                  task.guild_id
                    ? guildPath(task.guild_id, `/tasks/${task.id}`)
                    : `/tasks/${task.id}`
                )
              }
            >
              <CheckSquare className="text-muted-foreground" />
              <span>{task.title}</span>
            </CommandItem>
          ))}
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}
