/**
 * Editing state for one dashboard's canvas.
 *
 * Holds the definition being edited locally and pushes it to the API on a
 * debounce, because a drag fires a layout change on every settle and each one is
 * a whole-definition PATCH. Local state is the source of truth while edits are
 * in flight; the server's normalized response takes over once they land, which
 * is what makes clamping and validation authoritative without the canvas
 * flickering back mid-drag.
 *
 * No CRDT here on purpose: a dashboard layout is small and rarely co-edited, so
 * last-write-wins on the row is the right cost — unlike documents.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { DashboardRead, WidgetCatalog } from "@/api/generated/initiativeAPI.schemas";
import { useUpdateDashboard } from "@/hooks/useDashboards";
import {
  addWidget as addWidgetTo,
  type DashboardDefinition,
  type DefinitionWidget,
  definitionsEqual,
  pruneConfig,
  readConfig,
  readDefinition,
  removeWidget as removeWidgetFrom,
  updateWidget as updateWidgetIn,
} from "@/lib/widgets/definition";

/** Long enough that a drag settles into one request, short enough that the save
 *  feels immediate. */
const SAVE_DEBOUNCE_MS = 600;

export interface DashboardEditor {
  definition: DashboardDefinition;
  config: ReturnType<typeof readConfig>;
  isSaving: boolean;
  addWidget: (typeOrPreset: string, source: string) => void;
  removeWidget: (widgetId: string) => void;
  updateWidget: (widgetId: string, patch: Partial<DefinitionWidget>) => void;
  replaceDefinition: (next: DashboardDefinition) => void;
}

export function useDashboardEditor(
  dashboard: DashboardRead | undefined,
  catalog: WidgetCatalog | undefined,
  canEdit: boolean
): DashboardEditor {
  const update = useUpdateDashboard(dashboard?.id ?? 0);
  const [draft, setDraft] = useState<DashboardDefinition | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pending = useRef<DashboardDefinition | null>(null);

  const stored = useMemo(() => readDefinition(dashboard?.definition), [dashboard?.definition]);
  const config = useMemo(() => readConfig(dashboard?.config), [dashboard?.config]);
  const definition = draft ?? stored;

  const dashboardId = dashboard?.id;

  const flush = useCallback(() => {
    const next = pending.current;
    pending.current = null;
    if (!next || !dashboardId) return;
    const saved = JSON.stringify(next);
    update.mutate(
      {
        // The API types these JSON columns as open records; the shapes they
        // actually hold are `definition.ts`'s, and the server re-validates.
        definition: next as unknown as Record<string, unknown>,
        config: pruneConfig(next, config) as unknown as Record<string, unknown>,
      },
      {
        onSuccess: () => {
          // Hand control back to the server's copy only if the draft is still
          // what we just saved. Drags land faster than requests return, so an
          // unconditional reset would drop whatever the user did while this
          // was in flight — and an out-of-order response would drop it even
          // after a newer save had already succeeded.
          setDraft((current) =>
            current !== null && JSON.stringify(current) === saved ? null : current
          );
        },
      }
    );
  }, [dashboardId, config, update.mutate]);

  const save = useCallback(
    (next: DashboardDefinition) => {
      if (!canEdit) return;
      pending.current = next;
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(flush, SAVE_DEBOUNCE_MS);
    },
    [canEdit, flush]
  );

  // A pending edit must not be lost to a navigation. Held through a ref and
  // depended on nothing: with `flush` in the dependency list this effect
  // re-runs whenever its identity changes, and *its cleanup* then flushes on
  // an ordinary re-render — which silently turned the debounce into a save per
  // keystroke and per drag frame.
  const flushRef = useRef(flush);
  flushRef.current = flush;
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
      if (pending.current) flushRef.current();
    },
    []
  );

  const apply = useCallback(
    (next: DashboardDefinition) => {
      setDraft(next);
      save(next);
    },
    [save]
  );

  return {
    definition,
    config,
    isSaving: update.isPending,
    addWidget: useCallback(
      (typeOrPreset: string, source: string) =>
        apply(addWidgetTo(definition, catalog, typeOrPreset, source)),
      [apply, definition, catalog]
    ),
    removeWidget: useCallback(
      (widgetId: string) => apply(removeWidgetFrom(definition, widgetId)),
      [apply, definition]
    ),
    updateWidget: useCallback(
      (widgetId: string, patch: Partial<DefinitionWidget>) =>
        apply(updateWidgetIn(definition, widgetId, patch)),
      [apply, definition]
    ),
    replaceDefinition: useCallback(
      (next: DashboardDefinition) => {
        // Layout callbacks fire constantly; only a real change is worth a save.
        if (definitionsEqual(next, definition)) return;
        apply(next);
      },
      [apply, definition]
    ),
  };
}
