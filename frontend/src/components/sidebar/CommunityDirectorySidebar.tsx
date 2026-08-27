/**
 * The community directory's filters, in the app's own sidebar.
 *
 * The directory is a place you browse rather than a page you read, so what
 * narrows it sits where everywhere else in the app keeps its navigation — the
 * sidebar — and the page beside it is nothing but the cards.
 *
 * Both filters live in the URL. The sidebar writes them and the page reads
 * them, which is how two components on opposite sides of the layout agree
 * without a provider strung between them, and it leaves a filtered directory
 * linkable and reload-proof besides.
 *
 * The shelves are links, so a category can be opened in a new tab like anything
 * else, and each carries the current search along rather than clearing it.
 * Typing is debounced before it reaches the URL, and lands with `replace`, so a
 * search is one history entry rather than one per keystroke.
 */

import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Input } from "@/components/ui/input";
import {
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { asGuildCategory, GUILD_CATEGORIES, guildCategoryLabel } from "@/lib/guildCategories";

/** Long enough that a pause reads as "done typing", short enough that results
 *  arrive while the reader is still looking at the box. */
const TYPING_SETTLES_MS = 250;

export const CommunityDirectorySidebar = () => {
  const { t } = useTranslation(["guilds", "common"]);
  const navigate = useNavigate();
  // Read loosely rather than through the route: this renders inside the app
  // shell, which is mounted above the route that declares these params.
  const search = useSearch({ strict: false }) as { category?: unknown; q?: unknown };
  const category = asGuildCategory(search.category);
  const committed = typeof search.q === "string" ? search.q : "";

  // The box is answerable to the keystroke; the URL is answerable to the pause.
  const [draft, setDraft] = useState(committed);
  const settled = useDebouncedValue(draft, TYPING_SETTLES_MS);

  useEffect(() => {
    if (settled === committed) return;
    void navigate({
      to: "/communities",
      search: (prev: Record<string, unknown>) => ({
        ...prev,
        q: settled.trim() ? settled : undefined,
      }),
      replace: true,
    });
  }, [settled, committed, navigate]);

  const shelf = (value: (typeof GUILD_CATEGORIES)[number] | undefined, label: string) => (
    <SidebarMenuItem key={value ?? "all"}>
      <SidebarMenuButton asChild isActive={category === value}>
        <Link
          to="/communities"
          search={(prev: Record<string, unknown>) => ({ ...prev, category: value })}
        >
          <span className="truncate">{label}</span>
        </Link>
      </SidebarMenuButton>
    </SidebarMenuItem>
  );

  return (
    <>
      <SidebarHeader
        className="gap-0 border-b p-0"
        style={{ paddingTop: "var(--safe-area-inset-top)" }}
      >
        <div className="flex h-12 min-w-0 items-center gap-2 px-2.5">
          <h2 className="min-w-0 flex-1 truncate font-semibold text-lg">
            {t("guilds:community.title")}
          </h2>
        </div>
      </SidebarHeader>
      <SidebarContent className="h-full overflow-y-auto overflow-x-hidden">
        <SidebarGroup>
          <SidebarGroupContent>
            <Input
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder={t("guilds:community.searchPlaceholder")}
              aria-label={t("guilds:community.searchPlaceholder")}
            />
          </SidebarGroupContent>
        </SidebarGroup>
        <SidebarGroup>
          <SidebarGroupLabel>{t("guilds:community.categoriesHeading")}</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {shelf(undefined, t("guilds:community.allCategories"))}
              {GUILD_CATEGORIES.map((value) => shelf(value, guildCategoryLabel(value, t)))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
    </>
  );
};
