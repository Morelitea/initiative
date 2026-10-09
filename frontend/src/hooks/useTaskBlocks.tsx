/**
 * The plug-in blocks a screen's tasks are offered, asked for once per screen.
 *
 * A board or a task page calls this once, and hands what it returns to its
 * `<Section blocks>`: no card asks for anything of its own. A block is offered
 * where its install is enabled, the server says it opens in the tasks'
 * initiative (`block_access`), it fits one of the section's areas, and, when it
 * names a project listing, the project was installed from that listing.
 *
 * Each block that reads an endpoint makes one call for every task the screen
 * has loaded (in chunks of the contract's `blockSubjectIds`), not one per card.
 * Its rows are read again when the plug-in says they are stale
 * (`useRealtimeUpdates`), and an action's answer replaces its task's row.
 */

import {
  keepPreviousData,
  type QueryObserverResult,
  useQueries,
  useQueryClient,
} from "@tanstack/react-query";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { TaskListRead } from "@/api/generated/initiativeAPI.schemas";
import {
  getPluginBlockRows,
  type PluginBlockRequest,
  runPluginBlockAction,
} from "@/api/pluginData";
import {
  type BlockRows,
  type BlockShared,
  type OfferedBlock,
  PluginBlockArea,
} from "@/components/plugins/PluginBlocks";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityPlugins } from "@/hooks/useCommunityPlugins";
import { pluginBlockRowsKey } from "@/hooks/usePluginData";
import { useWidthClass } from "@/hooks/useWidthClass";
import { compileBlock } from "@/lib/blocks/blockTemplate";
import { communityPath } from "@/lib/communityUrl";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import {
  declaredBlocks,
  endpointKey,
  initiativePluginPath,
  type PluginBlock,
  pluginPages,
} from "@/lib/pluginSurfaces";
import type { CompileResult } from "@/lib/templates/compile";
import { type BlockAreaKind, SECTIONS, type SectionBlocks } from "@/lib/templates/sections";
import { BLOCK_SUBJECT_IDS } from "@/lib/templates/vocabulary";
import type { EndpointReturn } from "@/lib/widgets/pluginTemplate";
import { localized } from "@/lib/widgets/widgetMeta";
import type { TranslateFn } from "@/types/i18n";

type Rows = Record<string, Record<string, unknown>>;

/** Each block template, compiled once however many tasks draw it. */
const compiledBlocks = new Map<string, CompileResult>();

const compiled = (block: PluginBlock, definition: Record<string, unknown>): CompileResult => {
  const endpoints = Array.isArray(definition.endpoints)
    ? (definition.endpoints as { id?: string; returns?: EndpointReturn[] }[])
    : [];
  const returns = endpoints.find((endpoint) => endpoint.id === block.endpoint)?.returns ?? [];
  const strings = Object.keys(block.strings ?? {});
  const actions = (block.actions ?? []).map((id) => endpointKey(definition, id));
  const pages = Array.isArray(definition.pages)
    ? (definition.pages as { id?: unknown }[]).flatMap((page) =>
        typeof page.id === "string" ? [page.id] : []
      )
    : [];
  const key = JSON.stringify([block.template, returns, strings, actions, pages]);
  let result = compiledBlocks.get(key);
  if (!result) {
    result = compileBlock(block.template, returns, strings, actions, pages);
    compiledBlocks.set(key, result);
  }
  return result;
};

/** All of a block's rows for these tasks, a chunk per call. */
const readRows = async (request: PluginBlockRequest, taskIds: readonly number[]): Promise<Rows> => {
  const chunks: number[][] = [];
  for (let start = 0; start < taskIds.length; start += BLOCK_SUBJECT_IDS) {
    chunks.push(taskIds.slice(start, start + BLOCK_SUBJECT_IDS));
  }
  const answers = await Promise.all(chunks.map((chunk) => getPluginBlockRows(request, chunk)));
  return Object.assign({}, ...answers.map((answer) => answer.rows));
};

const asBlockRows = (results: QueryObserverResult<Rows>[]): BlockRows[] =>
  results.map((result) => ({
    rows: result.data,
    pending: result.isPending,
    failed: result.isError && !result.data,
  }));

const thisMinute = () => Math.floor(Date.now() / 60_000) * 60_000;

/** The screen's project, as far as a block cares: its initiative, and the listing it was
 *  installed from. */
export interface ListedProject {
  initiative_id: number;
  listing_uid?: string | null;
}

export interface TaskBlocksScope {
  /** The project the screen's tasks are in; absent, nothing is offered. */
  project: ListedProject | null | undefined;
  /** Every task the screen has loaded. */
  taskIds: readonly number[];
}

export function useTaskBlocks<S extends "task.card" | "task.page">(
  section: S,
  { project, taskIds }: TaskBlocksScope
): SectionBlocks<S> | undefined {
  const communityId = useActiveCommunityId();
  const { t, i18n } = useTranslation("plugins");
  const width = useWidthClass();
  const queryClient = useQueryClient();
  const { data: plugins } = useCommunityPlugins();
  const initiativeId = project?.initiative_id;
  const projectListing = project?.listing_uid ?? null;

  const offered = useMemo((): OfferedBlock[] => {
    if (!initiativeId) return [];
    const prefix = `${section}.`;
    return (plugins?.items ?? []).flatMap((plugin) => {
      if (!plugin.enabled) return [];
      const definition = plugin.definition;
      const opens = new Set(
        plugin.block_access
          .filter((access) => access.openable_initiatives.includes(initiativeId))
          .map((access) => access.block_id)
      );
      const pluginPath = initiativePluginPath(plugin, initiativeId);
      const openPages = new Set(pluginPages(plugin, initiativeId).map((page) => page.id));
      return declaredBlocks(definition).flatMap((block): OfferedBlock[] => {
        if (!opens.has(block.id)) return [];
        if (block.project_listing && block.project_listing !== projectListing) return [];
        const areas = block.areas.flatMap((area) =>
          area.startsWith(prefix) ? [area.slice(prefix.length)] : []
        );
        if (!areas.length) return [];
        const name = localized(block.name, i18n.language) ?? block.id;
        return [
          {
            key: `${plugin.id}:${block.id}`,
            request: { communityId, pluginId: plugin.id, blockId: block.id },
            areas: new Set(areas),
            name,
            label: t("blocks.label", { block: name, plugin: plugin.name }),
            strings: Object.fromEntries(
              Object.entries(block.strings ?? {}).map(([key, text]) => [
                key,
                localized(text, i18n.language) ?? key,
              ])
            ),
            compiled: compiled(block, definition),
            pagePath: (pageId) =>
              pluginPath && openPages.has(pageId) ? communityPath(communityId, pluginPath) : null,
            reads: Boolean(block.endpoint),
          },
        ];
      });
    });
  }, [plugins, initiativeId, projectListing, section, communityId, i18n.language, t]);

  const ids = useMemo(
    () => [...new Set(taskIds)].filter(Number.isFinite).sort((a, b) => a - b),
    [taskIds]
  );
  const reading = useMemo(() => offered.filter((block) => block.reads), [offered]);
  const rows = useQueries({
    queries: reading.map((block) => ({
      queryKey: pluginBlockRowsKey(
        communityId,
        block.request.pluginId,
        block.request.blockId,
        ids.join(",")
      ),
      queryFn: () => readRows(block.request, ids),
      enabled: ids.length > 0,
      // A task added to the board keeps every other card's block while the rows are read again.
      placeholderData: keepPreviousData,
    })),
    combine: asBlockRows,
  });

  return useMemo(() => {
    if (!offered.length) return undefined;
    const rowsByBlock = new Map(
      reading.map((block, index) => [block.key, rows[index] as BlockRows])
    );
    const shared: BlockShared = {
      t: t as TranslateFn,
      width,
      now: thisMinute(),
      run: async (block, actionKey, taskId) => {
        try {
          const { row } = await runPluginBlockAction(block.request, actionKey, taskId);
          const { pluginId, blockId } = block.request;
          queryClient.setQueriesData<Rows>(
            { queryKey: pluginBlockRowsKey(communityId, pluginId, blockId) },
            (current) => {
              if (!current) return current;
              const others = Object.fromEntries(
                Object.entries(current).filter(([id]) => id !== String(taskId))
              );
              return row ? { ...others, [taskId]: row } : others;
            }
          );
        } catch (error) {
          toast.error(getErrorMessage(error, "plugins:blocks.actionFailed"));
        }
      },
    };
    const areas: Readonly<Record<string, BlockAreaKind>> = SECTIONS[section].areas;
    const draw = (area: string, data: { task: TaskListRead }, className: string | undefined) => {
      const here = offered.filter((block) => block.areas.has(area));
      const kind = areas[area];
      if (!here.length || !kind) return null;
      return (
        <PluginBlockArea
          kind={kind}
          blocks={here}
          rows={rowsByBlock}
          task={data.task}
          className={className}
          shared={shared}
        />
      );
    };
    return draw as SectionBlocks<S>;
  }, [offered, reading, rows, t, width, queryClient, communityId, section]);
}
