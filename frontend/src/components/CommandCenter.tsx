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
  Search,
  Settings,
  ShieldCheck,
  UserCog,
  Users,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { SearchSuggestion } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { getOpenCreateDocumentWizard } from "@/components/documents/CreateDocumentWizard";
import { getOpenCreateTaskWizard } from "@/components/tasks/CreateTaskWizard";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
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
import { useGlobalCreateAccess } from "@/hooks/useInitiativeAccess";
import { useRecents } from "@/hooks/useRecents";
import { useGuildSearchSuggest } from "@/hooks/useSearch";
import { useTasks } from "@/hooks/useTasks";
import { useUserSearch } from "@/hooks/useUsers";
import { commandFilter } from "@/lib/fuzzyMatch";
import { guildPath, useGuildPath } from "@/lib/guildUrl";
import { canAccessAdminDashboard, canManagePlatformConfig } from "@/lib/permissions";
import { renderRecentIcon } from "@/lib/recentIcon";
import { recentRoute } from "@/lib/recentRoute";
import {
  categoryEntityTypes,
  DEFAULT_SEARCH_CATEGORY,
  hitIcon,
  SEARCH_CATEGORIES,
  type SearchCategory,
  searchHitPath,
} from "@/lib/searchResults";
import { PALETTE_TOOLS, TOOL_PALETTE } from "@/lib/toolPalette";
import { entityRefRoute, TOOL_ICONS, toolGuildBrowseTarget } from "@/lib/tools";
import {
  getAvatarSrc,
  getInitialsForUser,
  getUrlHandle,
  getUserDisplayName,
} from "@/lib/userDisplay";
import { cn } from "@/lib/utils";

// Module-level callback so other components can open the command center
let openCommandCenter: (() => void) | null = null;
export function getOpenCommandCenter() {
  return openCommandCenter;
}

/** How many people the palette offers at once — it is a way to reach one,
 *  not a roster. */
const PALETTE_MEMBER_LIMIT = 5;

export function CommandCenter() {
  const [open, setOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  // Which slice of the guild the results are from — the same three the results
  // page is split into, opening on the same one.
  const [scope, setScope] = useState<SearchCategory>(DEFAULT_SEARCH_CATEGORY);
  const { t } = useTranslation(["command", "common", "search"]);
  const router = useRouter();
  const { user } = useAuth();
  const { activeGuild, activeGuildId } = useGuilds();
  const globalCreate = useGlobalCreateAccess();
  const getGuildPath = useGuildPath();
  /** The guild home showing one tool — the cross-initiative browse surface. */
  const guildBrowsePath = useCallback(
    (tool: Tool) => {
      const target = toolGuildBrowseTarget(tool);
      return `${getGuildPath(target.to)}?tool=${target.search.tool}`;
    },
    [getGuildPath]
  );

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
    if (!open) {
      setSearchQuery("");
      setScope(DEFAULT_SEARCH_CATEGORY);
    }
  }, [open]);

  // Tab moves between the slices while there is something to search for, so the
  // hands stay on the query.
  //
  // Only forward, and only from the input: Shift+Tab is left alone, so focus
  // can still walk the dialog and reach the strip, the close button and
  // everything else by keyboard.
  useEffect(() => {
    if (!open || !isSearching) return;
    const handleTab = (event: KeyboardEvent) => {
      if (event.key !== "Tab" || event.shiftKey) return;
      const target = event.target as HTMLElement | null;
      if (!target?.hasAttribute("cmdk-input")) return;
      event.preventDefault();
      setScope((current) => {
        const next = SEARCH_CATEGORIES.indexOf(current) + 1;
        return SEARCH_CATEGORIES[next % SEARCH_CATEGORIES.length];
      });
    };
    document.addEventListener("keydown", handleTab);
    return () => document.removeEventListener("keydown", handleTab);
  }, [open, isSearching]);

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
  // Searching asks the guild index one question and gets every kind of thing
  // back — tasks, documents, queue items, events, tags — ranked together.
  // `null` for Members, who are not in the index: identity is shared across
  // communities while the index is per-community, so they are read from the
  // roster — the same split the results page makes.
  const scopeTypes = categoryEntityTypes(scope);
  const isMemberScope = scopeTypes === null;
  const suggestQuery = useGuildSearchSuggest(effectiveSearch, {
    enabled: open && !!user && isSearching && !isMemberScope,
    types: scopeTypes ?? undefined,
    staleTime: 30_000,
  });
  const membersQuery = useUserSearch({
    search: effectiveSearch,
    pageSize: PALETTE_MEMBER_LIMIT,
    enabled: open && !!user && isSearching && isMemberScope,
  });
  // Whichever of the two the reader is on — the other is switched off, and a
  // switched-off question keeps the answer it was last given, which belongs to
  // the tab before this one. Only the scope being read may put rows on screen
  // or say there are none.
  const scopeQuery = isMemberScope ? membersQuery : suggestQuery;
  // Browsing (palette just opened): the user's own not-done tasks, most
  // recently updated — surfacing what they're actively working on. Fired once
  // on open, so the full list row is fine.
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
  // Browse rows carry their own guild_id — a task in this list can come from
  // any guild the user is in.
  const tasks = useMemo(
    () =>
      (browseTasksQuery.data?.items ?? []).map((task) => ({
        id: task.id,
        title: task.title,
        guildId: task.guild_id ?? activeGuildId,
      })),
    [browseTasksQuery.data, activeGuildId]
  );

  // Only what has somewhere to go: an entry that cannot navigate is worse than
  // one that isn't offered.
  const suggestions = useMemo(
    () =>
      isMemberScope
        ? []
        : (suggestQuery.data ?? [])
            .map((hit) => ({ hit, path: searchHitPath(hit) }))
            .filter((row): row is { hit: SearchSuggestion; path: string } => row.path !== null),
    [suggestQuery.data, isMemberScope]
  );

  const members = isMemberScope ? (membersQuery.data?.items ?? []) : [];
  // Nothing is here, and that is this scope's own answer rather than a gap
  // before it arrives: a tab that found nobody says so instead of leaving the
  // rows before it standing. A question that never got an answer is a third
  // thing again — "nobody matched" would be a claim about a community nothing
  // has been read from.
  const scopeIsEmpty =
    members.length === 0 &&
    suggestions.length === 0 &&
    scopeQuery.isSuccess &&
    !scopeQuery.isPlaceholderData;

  const isGuildAdmin = activeGuild?.role === "admin";
  const showPlatformSettings = canManagePlatformConfig(user);
  const showAdminDashboard = canAccessAdminDashboard(user);

  // Static pages
  const pages = useMemo(() => {
    const items = [
      { label: t("pages.myTasks"), path: "/", icon: CheckSquare },
      { label: t("pages.tasksICreated"), path: "/created-tasks", icon: PenLine },
      { label: t("pages.myCalendar"), path: "/my-calendar", icon: CalendarDays },
      { label: t("pages.myProjects"), path: "/my-projects", icon: ListTodo },
      { label: t("pages.myDocuments"), path: "/my-documents", icon: ScrollText },
      { label: t("pages.myContacts"), path: "/contacts", icon: Users },
      { label: t("pages.myStats"), path: "/user-stats", icon: BarChart3 },
      { label: t("pages.userSettings"), path: "/profile", icon: UserCog },
      // Tools are browsed across initiatives on the guild home, which names
      // the one it is showing in its search — there is no guild-wide list page.
      {
        label: t("pages.allProjects"),
        path: guildBrowsePath(Tool.project),
        icon: ListTodo,
      },
      {
        label: t("pages.allDocuments"),
        path: guildBrowsePath(Tool.document),
        icon: ScrollText,
      },
      {
        label: t("pages.allInitiatives"),
        path: getGuildPath("/"),
        icon: Users,
      },
    ];

    if (isGuildAdmin) {
      items.push({
        label: t("pages.guildSettings"),
        path: getGuildPath("/settings"),
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
  }, [t, getGuildPath, guildBrowsePath, isGuildAdmin, showAdminDashboard, showPlatformSettings]);

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
      {isSearching && (
        <div
          className="flex items-center gap-1 border-b px-2 py-1.5"
          role="tablist"
          aria-label={t("search:title")}
        >
          {SEARCH_CATEGORIES.map((category) => (
            <button
              key={category}
              type="button"
              role="tab"
              aria-selected={scope === category}
              onClick={() => setScope(category)}
              className={cn(
                "rounded-md px-2 py-1 text-sm transition-colors",
                scope === category
                  ? "bg-accent font-medium text-accent-foreground"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              {t(`search:tabs.${category}`)}
            </button>
          ))}
          <span className="ml-auto pr-1 text-muted-foreground text-xs">
            {t("search:switchHint")}
          </span>
        </div>
      )}

      <CommandList>
        <CommandEmpty>{t("noResults")}</CommandEmpty>

        {/* What the guild index found — first, so the top hit is what Enter
            opens. The server has already decided these match, so they are
            keyed on the query itself rather than re-filtered here. */}
        {isSearching && (
          <CommandGroup heading={t("groups.results")}>
            {members.map((member) => (
              // A profile belongs to the person rather than to the community
              // the search ran in, so this leaves the community tree.
              <CommandItem
                key={`member-${member.id}`}
                value={`member-${member.id}`}
                keywords={[effectiveSearch, getUserDisplayName(member)]}
                onSelect={() => handleSelect(`/u/${getUrlHandle(member)}`)}
              >
                <Avatar className="size-4">
                  <AvatarImage src={getAvatarSrc(member)} alt="" />
                  <AvatarFallback className="text-[9px]">
                    {getInitialsForUser(member)}
                  </AvatarFallback>
                </Avatar>
                <span>{getUserDisplayName(member)}</span>
              </CommandItem>
            ))}
            {suggestions.map(({ hit, path }) => {
              const Icon = hitIcon(hit);
              return (
                <CommandItem
                  key={`result-${hit.entity_type}-${hit.entity_id}`}
                  value={`result-${hit.entity_type}-${hit.entity_id}`}
                  keywords={[effectiveSearch, hit.title]}
                  onSelect={() =>
                    handleSelect(activeGuildId ? guildPath(activeGuildId, path) : path)
                  }
                >
                  <Icon className="text-muted-foreground" />
                  <span>{hit.title}</span>
                </CommandItem>
              );
            })}
            {(scopeQuery.isError || scopeIsEmpty) && (
              <div className="py-3 text-center text-muted-foreground text-sm">
                {scopeQuery.isError ? t("search:failed.title") : t("noResults")}
              </div>
            )}
            {activeGuildId !== null && (
              <CommandItem
                value="result-see-all"
                keywords={[effectiveSearch]}
                onSelect={() =>
                  handleSelect(
                    `${getGuildPath("/search")}?q=${encodeURIComponent(effectiveSearch)}` +
                      (scope === DEFAULT_SEARCH_CATEGORY ? "" : `&tab=${scope}`)
                  )
                }
              >
                <Search className="text-muted-foreground" />
                <span>{t("seeAllResults", { query: effectiveSearch })}</span>
              </CommandItem>
            )}
          </CommandGroup>
        )}

        {/* Actions — each shown only when the user can land its wizard
            somewhere (cmdk hides the group if it ends up empty). */}
        <CommandGroup heading={t("groups.actions")}>
          {globalCreate.task && (
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
          )}
          {globalCreate.document && (
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
          )}
        </CommandGroup>

        {/* Suggested — mixed recents across projects/documents/queues/counter
            groups. Browsing only: once there is a query, the index answers. */}
        {!isSearching && recentItems.length > 0 && (
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

        {/* Browsing only: one group per tool, and the tasks you are working
            on. While searching, the index answers for every kind at once —
            these would repeat it a tool at a time. */}
        {!isSearching &&
          PALETTE_TOOLS.map((tool) => (
            <ToolPaletteGroup
              key={tool}
              tool={tool}
              enabled={open && !!user}
              activeGuildId={activeGuildId}
              onSelect={handleSelect}
            />
          ))}

        {!isSearching && (
          <CommandGroup heading={t("groups.tasks")}>
            {tasks.map((task) => (
              <CommandItem
                key={`task-${task.id}`}
                value={`task-${task.id}-${task.title}`}
                onSelect={() =>
                  handleSelect(
                    // Cross-guild rows carry no initiative, so the resolver
                    // works out the address on the way in.
                    task.guildId
                      ? guildPath(task.guildId, entityRefRoute("task", task.id))
                      : entityRefRoute("task", task.id)
                  )
                }
              >
                <CheckSquare className="text-muted-foreground" />
                <span>{task.title}</span>
              </CommandItem>
            ))}
          </CommandGroup>
        )}
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
  activeGuildId,
  onSelect,
}: {
  tool: (typeof PALETTE_TOOLS)[number];
  enabled: boolean;
  activeGuildId: number | null;
  onSelect: (path: string) => void;
}) {
  const heading = TOOL_PALETTE[tool].useHeading();
  const items = TOOL_PALETTE[tool].useItems({ enabled });
  if (heading === null) return null;
  const Icon = TOOL_ICONS[tool];
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
