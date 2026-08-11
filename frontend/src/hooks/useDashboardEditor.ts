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
  canonicalJson,
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
  addWidget: (typeOrPreset: string, source: string, options?: Record<string, string>) => void;
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
  const inFlight = useRef(false);

  const stored = useMemo(() => readDefinition(dashboard?.definition), [dashboard?.definition]);
  const config = useMemo(() => readConfig(dashboard?.config), [dashboard?.config]);
  const definition = draft ?? stored;

  const dashboardId = dashboard?.id;

  // Declared before `flush` because `flush` re-enters through it (a queued save
  // fires from the previous one's settle) and because the unmount effect below
  // must not depend on `flush`'s identity.
  const flushRef = useRef<(force?: boolean) => void>(() => {});

  /**
   * Send the pending definition, at most one request at a time.
   *
   * Each save is a whole-definition PATCH, so two in flight together can commit
   * in either order and leave the *older* one authoritative — the layout the
   * user last arranged, silently replaced on the next refetch. The API carries
   * no revision to check, and the design accepts last-write-wins between
   * different editors; what it must not do is let one editor race itself. So a
   * save waits for the one before it, and whatever accumulated meanwhile goes
   * next, in order.
   *
   * `force` is for unmount, where waiting is not an option: sending a queued
   * edit risks the ordering we otherwise avoid, but not sending it loses that
   * edit outright.
   */
  const flush = useCallback(
    (force = false) => {
      if (inFlight.current && !force) return;
      const next = pending.current;
      pending.current = null;
      if (!next || !dashboardId) return;

      const saved = canonicalJson(next);
      inFlight.current = true;
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
            // was in flight. The mutation seeds the dashboard cache with its own
            // response first, so "the server's copy" here is already this save's
            // — the canvas does not fall back to the pre-save layout.
            setDraft((current) =>
              current !== null && canonicalJson(current) === saved ? null : current
            );
          },
          onSettled: () => {
            inFlight.current = false;
            // Anything queued while this was on the wire goes now, so the last
            // arrangement the user made is the last one the server sees.
            if (pending.current) flushRef.current();
          },
        }
      );
    },
    [dashboardId, config, update.mutate]
  );

  const save = useCallback(
    (next: DashboardDefinition) => {
      if (!canEdit) return;
      pending.current = next;
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => flush(), SAVE_DEBOUNCE_MS);
    },
    [canEdit, flush]
  );

  flushRef.current = flush;

  // A pending edit must not be lost to a navigation. This effect depends on
  // nothing: with `flush` in the dependency list it re-runs whenever that
  // identity changes, and *its cleanup* then flushes on an ordinary re-render —
  // which silently turned the debounce into a save per drag frame.
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
      if (pending.current) flushRef.current(true);
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
      (typeOrPreset: string, source: string, options?: Record<string, string>) =>
        apply(addWidgetTo(definition, catalog, typeOrPreset, source, options)),
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
