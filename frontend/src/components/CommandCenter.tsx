import { useRouter } from "@tanstack/react-router";
import {
  BarChart3,
  CalendarDays,
  CheckSquare,
  FilePlus,
  ListTodo,
  PenLine,
  Plus,
  ScrollText,
  Settings,
  ShieldCheck,
  UserCog,
  Users,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { getOpenCreateDocumentWizard } from "@/components/documents/CreateDocumentWizard";
import { getOpenCreateTaskWizard } from "@/components/tasks/CreateTaskWizard";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { useAuth } from "@/hooks/useAuth";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useGuilds } from "@/hooks/useGuilds";
import { useRecents } from "@/hooks/useRecents";
import { useTaskAutocomplete, useTasks } from "@/hooks/useTasks";
import { commandFilter } from "@/lib/fuzzyMatch";
import { guildPath, useGuildPath } from "@/lib/guildUrl";
import { canAccessAdminDashboard, canManagePlatformConfig } from "@/lib/permissions";
import { renderRecentIcon } from "@/lib/recentIcon";
import { recentRoute } from "@/lib/recentRoute";
import { PALETTE_TOOLS, TOOL_PALETTE } from "@/lib/toolPalette";
import { TOOL_REGISTRY } from "@/lib/tools";

// Module-level callback so other components can open the command center
let openCommandCenter: (() => void) | null = null;
export function getOpenCommandCenter() {
  return openCommandCenter;
}

export function CommandCenter() {
  const [open, setOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const { t } = useTranslation(["command", "common"]);
  const router = useRouter();
  const { user } = useAuth();
  const { activeGuild, activeGuildId } = useGuilds();
  const getGuildPath = useGuildPath();

  // Switch into "guild-wide title search" mode once the debounced query is at
  // least 2 characters. Single-character queries fire too noisily and rarely
  // narrow enough to be useful. If the raw input is already empty (e.g.
  // immediately after dialog close) treat the debounced value as empty too,
  // so a quick close+reopen within the 200 ms window doesn't briefly fall
  // into search mode against the stale prior query.
  const trimmedQuery = searchQuery.trim();
  const debouncedSearch = useDebouncedValue(trimmedQuery, 200);
  const effectiveSearch = trimmedQuery === "" ? "" : debouncedSearch;
  const isSearching = effectiveSearch.length >= 2;

  // Reset the input whenever the dialog closes so reopening starts fresh.
  useEffect(() => {
    if (!open) setSearchQuery("");
  }, [open]);

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
  const recentQuery = useRecents({ staleTime: 30_000 });
  // Two modes for the tasks source:
  //  - Searching: a slim id+title typeahead over the active guild's tasks (the
  //    hot, per-keystroke path). The palette only renders the title and
  //    navigates by id, so the heavy list row was pure overfetch here.
  const searchTasksQuery = useTaskAutocomplete(effectiveSearch, {
    enabled: open && !!user && isSearching,
    limit: 25,
    staleTime: 30_000,
  });
  //  - Browsing (palette just opened): the user's own not-done tasks, most
  //    recently updated — surfacing what they're actively working on. Fired
  //    once on open, so the full list row is fine.
  const browseTasksQuery = useTasks(
    {
      page_size: 25,
      conditions: user
        ? [
            { field: "assignee_ids", op: "in_" as const, value: [user.id] },
            {
              field: "status_category",
              op: "in_" as const,
              value: ["backlog", "todo", "in_progress"],
            },
          ]
        : [],
      sorting: [{ field: "updated_at", dir: "desc" as const }],
    },
    { enabled: open && !!user && !isSearching, staleTime: 30_000 }
  );

  // Suggested = mixed-type recent items, ordered by ``last_viewed_at`` desc
  // (same payload that backs the layout tabs bar).
  const recentItems = recentQuery.data ?? [];
  // Normalize both sources to the id/title/guild the palette actually renders.
  // Search rows come from the guild-scoped autocomplete (active guild); browse
  // rows carry their own guild_id.
  const tasks = useMemo(
    () =>
      isSearching
        ? (searchTasksQuery.data ?? []).map((task) => ({
            id: task.id,
            title: task.title,
            guildId: activeGuildId,
          }))
        : (browseTasksQuery.data?.items ?? []).map((task) => ({
            id: task.id,
            title: task.title,
            guildId: task.guild_id ?? activeGuildId,
          })),
    [isSearching, searchTasksQuery.data, browseTasksQuery.data, activeGuildId]
  );

  const isGuildAdmin = activeGuild?.role === "admin";
  const showPlatformSettings = canManagePlatformConfig(user);
  const showAdminDashboard = canAccessAdminDashboard(user);

  // Static pages
  const pages = useMemo(() => {
    const items = [
      { label: t("pages.myTasks"), path: "/", icon: CheckSquare },
      { label: t("pages.tasksICreated"), path: "/created-tasks", icon: PenLine },
      { label: t("pages.myCalendar"), path: "/my-calendar-events", icon: CalendarDays },
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

    if (showAdminDashboard) {
      items.push({
        label: t("pages.adminDashboard"),
        path: "/settings/admin",
        icon: ShieldCheck,
      });
    }

    if (showPlatformSettings) {
      items.push({
        label: t("pages.platformSettings"),
        path: "/settings/platform",
        icon: Settings,
      });
    }

    return items;
  }, [t, getGuildPath, isGuildAdmin, showAdminDashboard, showPlatformSettings]);

  const handleSelect = (path: string) => {
    setOpen(false);
    void router.navigate({ to: path });
  };

  return (
    <CommandDialog open={open} onOpenChange={setOpen} filter={commandFilter}>
      <CommandInput
        value={searchQuery}
        onValueChange={setSearchQuery}
        placeholder={t("placeholder", {
          activeGuildName: activeGuild?.name ?? t("common:appName"),
        })}
      />
      <CommandList>
        <CommandEmpty>{t("noResults")}</CommandEmpty>

        {/* Actions */}
        <CommandGroup heading={t("groups.actions")}>
          <CommandItem
            value="action-add-task"
            onSelect={() => {
              setOpen(false);
              getOpenCreateTaskWizard()?.();
            }}
          >
            <Plus className="text-muted-foreground" />
            <span>{t("actions.addTask")}</span>
          </CommandItem>
          <CommandItem
            value="action-add-document"
            onSelect={() => {
              setOpen(false);
              getOpenCreateDocumentWizard()?.();
            }}
          >
            <FilePlus className="text-muted-foreground" />
            <span>{t("actions.addDocument")}</span>
          </CommandItem>
        </CommandGroup>

        {/* Suggested — mixed recents across projects/documents/queues/counter
            groups (cmdk hides empty groups automatically when searching). */}
        {recentItems.length > 0 && (
          <CommandGroup heading={t("groups.suggested")}>
            {recentItems.slice(0, 5).map((item) => (
              <CommandItem
                key={`suggested-${item.guild_id}-${item.entity_type}-${item.entity_id}`}
                value={`suggested-${item.guild_id}-${item.entity_type}-${item.entity_id}-${item.name}`}
                keywords={[item.name]}
                onSelect={() => handleSelect(recentRoute(item))}
              >
                {renderRecentIcon(item) ?? <ListTodo className="text-muted-foreground" />}
                <span>{item.name}</span>
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

        {/* One group per palette-enabled tool (registry-driven) */}
        {PALETTE_TOOLS.map((tool) => (
          <ToolPaletteGroup
            key={tool}
            tool={tool}
            enabled={open && !!user}
            search={isSearching ? effectiveSearch : undefined}
            activeGuildId={activeGuildId}
            onSelect={handleSelect}
          />
        ))}

        {/* Tasks */}
        <CommandGroup heading={t("groups.tasks")}>
          {tasks.map((task) => (
            <CommandItem
              key={`task-${task.id}`}
              value={`task-${task.id}-${task.title}`}
              onSelect={() =>
                handleSelect(
                  task.guildId ? guildPath(task.guildId, `/tasks/${task.id}`) : `/tasks/${task.id}`
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

/**
 * One command-palette group for one tool — its own component so each tool's
 * palette source hook runs at a stable component boundary. Renders nothing
 * when the tool's heading resolves to null (e.g. no advanced-tool runtime
 * config).
 */
function ToolPaletteGroup({
  tool,
  enabled,
  search,
  activeGuildId,
  onSelect,
}: {
  tool: (typeof PALETTE_TOOLS)[number];
  enabled: boolean;
  search?: string;
  activeGuildId: number | null;
  onSelect: (path: string) => void;
}) {
  const heading = TOOL_PALETTE[tool].useHeading();
  const items = TOOL_PALETTE[tool].useItems({ enabled, search });
  if (heading === null) return null;
  const Icon = TOOL_REGISTRY[tool].icon;
  return (
    <CommandGroup heading={heading}>
      {items.map((item) => (
        <CommandItem
          key={`${tool}-${item.id}`}
          value={`${tool}-${item.id}-${item.label}`}
          keywords={item.keywords}
          onSelect={() => onSelect(activeGuildId ? guildPath(activeGuildId, item.path) : item.path)}
        >
          {item.icon ?? <Icon className="text-muted-foreground" />}
          <span>{item.label}</span>
        </CommandItem>
      ))}
    </CommandGroup>
  );
}
