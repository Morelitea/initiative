/**
 * Names for the ids a binding mentions — the viewer's own, or nothing.
 *
 * Provenance can only print a name the *reader* is allowed to see, so the
 * lookup below is an ordinary RLS-gated hook and membership in its result is
 * the entire authorization decision. Nothing here consults the definition for a
 * name, and nothing caches one across sessions.
 *
 * One kind of id survives the move to queries: the file a sheet range sits
 * in. A statement mentions no ids at all — it says which datasets it reads, and
 * the server answers that with the rows.
 */

import { useMemo } from "react";

import { useFile } from "@/hooks/useFiles";
import type { WidgetBinding } from "@/hooks/useWidgetData";
import { EMPTY_LABELS, type EntityLabels } from "@/lib/widgets/provenance";

export function useBindingLabels(
  binding: WidgetBinding,
  initiativeId: number | undefined,
  enabled = true
): EntityLabels {
  const scoped = enabled && typeof initiativeId === "number";
  const fileId = scoped ? (binding.file_id ?? null) : null;
  const fileQuery = useFile(fileId);

  return useMemo<EntityLabels>(() => {
    if (!scoped) return EMPTY_LABELS;
    const file = new Map<number, string>();
    // Held against the dashboard's own initiative, like every other id a
    // binding names: one pointing elsewhere resolves to nothing rather than to
    // a name from another initiative.
    if (
      fileQuery.data &&
      fileQuery.data.initiative_id === initiativeId &&
      typeof fileId === "number"
    ) {
      file.set(fileId, fileQuery.data.name);
    }
    return { file, ready: fileId === null || !fileQuery.isLoading };
  }, [scoped, initiativeId, fileId, fileQuery.data, fileQuery.isLoading]);
}
