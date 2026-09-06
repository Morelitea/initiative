/**
 * Per-tool command-palette sources — the ONE place a tool declares how its
 * entities surface in the command center: which query feeds it, what a row is
 * labelled, its keywords, icon, and target route.
 *
 * `CommandCenter` renders one group per tool with `commandPalette: true` in
 * the registry by mounting a `<ToolPaletteGroup>` per tool; each group calls
 * its own source hook here (a component boundary per group keeps the rules of
 * hooks happy). A new tool adds one entry — the drift test asserts every
 * palette-enabled tool has one.
 *
 * These groups are what the palette shows while BROWSING. Once there is
 * something to search for, the guild index answers instead, across every kind
 * of thing at once.
 */

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { useCalendarsList } from "@/hooks/useCalendars";
import { useCounterGroupsList } from "@/hooks/useCounters";
import { useDashboardsList } from "@/hooks/useDashboards";
import { useDocumentsList } from "@/hooks/useDocuments";
import { usePostsList } from "@/hooks/usePosts";
import { useProjects } from "@/hooks/useProjects";
import { useQueuesList } from "@/hooks/useQueues";
import { getDocumentIcon, getDocumentIconColor } from "@/lib/fileUtils";
import { TOOLS, toolCamelPlural, toolDetailRoute } from "@/lib/tools";
import { cn } from "@/lib/utils";

export interface PaletteItem {
  id: number;
  label: string;
  keywords: string[];
  /** Item icon; null falls back to the tool's registry icon. */
  icon: ReactNode | null;
  /** Guild-relative target path. */
  path: string;
}

export interface PaletteSourceContext {
  /** Only fetch while the palette is open for an authenticated user. */
  enabled: boolean;
}

export interface ToolPaletteSource {
  /** Group heading; null hides the group entirely (e.g. no runtime config). */
  useHeading: () => string | null;
  useItems: (ctx: PaletteSourceContext) => PaletteItem[];
}

const useGroupHeading = (tool: Tool): string => {
  const { t } = useTranslation("command");
  return t(`groups.${toolCamelPlural(tool)}` as never);
};

export const TOOL_PALETTE: Record<Tool, ToolPaletteSource> = {
  [Tool.project]: {
    useHeading: () => useGroupHeading(Tool.project),
    useItems: () => {
      const query = useProjects(undefined, { staleTime: 60_000 });
      return (query.data?.items ?? []).map((project) => ({
        id: project.id,
        label: project.name,
        keywords: [
          project.description ?? "",
          project.initiative?.name ?? "",
          ...(project.tags?.map((tag) => tag.name) ?? []),
        ],
        icon: project.icon ? <span className="text-base leading-none">{project.icon}</span> : null,
        path: toolDetailRoute(Tool.project, project.initiative_id, project.id),
      }));
    },
  },
  [Tool.document]: {
    useHeading: () => useGroupHeading(Tool.document),
    useItems: ({ enabled }) => {
      // The 25 most recently updated. Narrowing by what was typed is the
      // index's job now, and it answers for every tool at once.
      const query = useDocumentsList({ page_size: 25 }, { enabled, staleTime: 60_000 });
      return (query.data?.items ?? []).map((doc) => {
        const DocIcon = getDocumentIcon(
          doc.document_type,
          doc.file_content_type,
          doc.original_filename
        );
        const color = getDocumentIconColor(
          doc.document_type,
          doc.file_content_type,
          doc.original_filename
        );
        return {
          id: doc.id,
          label: doc.name,
          keywords: [doc.initiative?.name ?? "", ...(doc.tags?.map((tag) => tag.name) ?? [])],
          icon: <DocIcon className={cn(color)} />,
          path: toolDetailRoute(Tool.document, doc.initiative_id, doc.id),
        };
      });
    },
  },
  [Tool.queue]: {
    useHeading: () => useGroupHeading(Tool.queue),
    useItems: () => {
      const query = useQueuesList({ page_size: 100 }, { staleTime: 60_000 });
      return (query.data?.items ?? []).map((queue) => ({
        id: queue.id,
        label: queue.name,
        keywords: [queue.description ?? ""],
        icon: null,
        path: toolDetailRoute(Tool.queue, queue.initiative_id, queue.id),
      }));
    },
  },
  [Tool.counter_group]: {
    useHeading: () => useGroupHeading(Tool.counter_group),
    useItems: () => {
      const query = useCounterGroupsList({ page_size: 100 }, { staleTime: 60_000 });
      return (query.data?.items ?? []).map((group) => ({
        id: group.id,
        label: group.name,
        keywords: [group.description ?? ""],
        icon: null,
        path: toolDetailRoute(Tool.counter_group, group.initiative_id, group.id),
      }));
    },
  },
  [Tool.calendar]: {
    useHeading: () => useGroupHeading(Tool.calendar),
    useItems: ({ enabled }) => {
      const query = useCalendarsList({ page_size: 100 }, { enabled, staleTime: 60_000 });
      return (query.data?.items ?? []).map((calendar) => ({
        id: calendar.id,
        label: calendar.name,
        keywords: [calendar.description ?? ""],
        icon: null,
        path: toolDetailRoute(Tool.calendar, calendar.initiative_id, calendar.id),
      }));
    },
  },
  [Tool.dashboard]: {
    useHeading: () => useGroupHeading(Tool.dashboard),
    useItems: ({ enabled }) => {
      const query = useDashboardsList({ page_size: 100 }, { enabled, staleTime: 60_000 });
      return (query.data?.items ?? []).map((dashboard) => ({
        id: dashboard.id,
        label: dashboard.name,
        keywords: [dashboard.description ?? ""],
        icon: null,
        path: toolDetailRoute(Tool.dashboard, dashboard.initiative_id, dashboard.id),
      }));
    },
  },
  [Tool.post]: {
    useHeading: () => useGroupHeading(Tool.post),
    useItems: ({ enabled }) => {
      // A page rather than the usual 100: posts carry their bodies, so a
      // hundred of them is a hundred editor states pulled in to fill a
      // dropdown. The palette matches on headline and excerpt, both of which
      // the first page already has.
      const query = usePostsList({ page_size: 25 }, { enabled, staleTime: 60_000 });
      return (query.data?.items ?? []).map((post) => ({
        id: post.id,
        label: post.name,
        keywords: [post.excerpt],
        icon: null,
        path: toolDetailRoute(Tool.post, post.initiative_id, post.id),
      }));
    },
  },
};

/** Tools that get a command-palette group, in display order — every tool does. */
export const PALETTE_TOOLS: Tool[] = TOOLS;
