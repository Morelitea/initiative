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
 */

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useCalendarEventsList } from "@/hooks/useCalendarEvents";
import { useCounterGroupsList } from "@/hooks/useCounters";
import { useDocumentsList } from "@/hooks/useDocuments";
import { useInitiatives } from "@/hooks/useInitiatives";
import { useProjects } from "@/hooks/useProjects";
import { useQueuesList } from "@/hooks/useQueues";
import { getDocumentIcon, getDocumentIconColor } from "@/lib/fileUtils";
import { TOOL_REGISTRY, toolCamelPlural, toolListRoute } from "@/lib/tools";
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
  /** Server-side search once the input has enough characters (documents). */
  search?: string;
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
        path: `${toolListRoute(Tool.project)}/${project.id}`,
      }));
    },
  },
  [Tool.document]: {
    useHeading: () => useGroupHeading(Tool.document),
    useItems: ({ enabled, search }) => {
      // Default to the 25 most recently updated; swap to a server-side title
      // search once the input has ≥2 characters.
      const query = useDocumentsList(
        { page_size: 25, ...(search ? { search } : {}) },
        { enabled, staleTime: 60_000 }
      );
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
          label: doc.title,
          keywords: [doc.initiative?.name ?? "", ...(doc.tags?.map((tag) => tag.name) ?? [])],
          icon: <DocIcon className={cn(color)} />,
          path: `${toolListRoute(Tool.document)}/${doc.id}`,
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
        path: `${toolListRoute(Tool.queue)}/${queue.id}`,
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
        path: `${toolListRoute(Tool.counter_group)}/${group.id}`,
      }));
    },
  },
  [Tool.calendar_event]: {
    useHeading: () => useGroupHeading(Tool.calendar_event),
    useItems: ({ enabled }) => {
      const query = useCalendarEventsList({ page_size: 50 }, { enabled, staleTime: 60_000 });
      return (query.data?.items ?? []).map((event) => ({
        id: event.id,
        label: event.title,
        keywords: [event.description ?? ""],
        icon: null,
        path: `${toolListRoute(Tool.calendar_event)}/${event.id}`,
      }));
    },
  },
  [Tool.advanced_tool]: {
    // Heading is the deployment's own name for the tool; null (no runtime
    // config) hides the group.
    useHeading: () => {
      const { advancedTool } = useAppConfig();
      const fallback = useGroupHeading(Tool.advanced_tool);
      if (!advancedTool) return null;
      return advancedTool.name || fallback;
    },
    // One navigation entry per initiative with the tool enabled (a single
    // embedded page per initiative, not a searchable collection).
    useItems: ({ enabled }) => {
      const query = useInitiatives({ enabled, staleTime: 60_000 });
      return (query.data ?? [])
        .filter((initiative) => initiative.advanced_tools_enabled)
        .map((initiative) => ({
          id: initiative.id,
          label: initiative.name,
          keywords: [],
          icon: null,
          path: `/initiatives/${initiative.id}/advanced-tool`,
        }));
    },
  },
};

/** Registry-driven list of tools that get a palette group, in display order. */
export const PALETTE_TOOLS: Tool[] = (Object.values(Tool) as Tool[]).filter(
  (tool) => TOOL_REGISTRY[tool].commandPalette
);
