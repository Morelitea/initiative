/**
 * Names for the ids a binding mentions — the viewer's own, or nothing.
 *
 * Provenance can only print a name the *reader* is allowed to see, so the
 * lookup below is an ordinary RLS-gated hook and membership in its result is
 * the entire authorization decision. Nothing here consults the definition for a
 * name, and nothing caches one across sessions.
 *
 * One kind of id survives the move to queries: the document a sheet range sits
 * in. A statement mentions no ids at all — it says which datasets it reads, and
 * the server answers that with the rows.
 */

import { useMemo } from "react";

import { useDocument } from "@/hooks/useDocuments";
import type { WidgetBinding } from "@/hooks/useWidgetData";
import { EMPTY_LABELS, type EntityLabels } from "@/lib/widgets/provenance";

export function useBindingLabels(
  binding: WidgetBinding,
  initiativeId: number | undefined,
  enabled = true
): EntityLabels {
  const scoped = enabled && typeof initiativeId === "number";
  const documentId = scoped ? (binding.document_id ?? null) : null;
  const documentQuery = useDocument(documentId);

  return useMemo<EntityLabels>(() => {
    if (!scoped) return EMPTY_LABELS;
    const document = new Map<number, string>();
    // Held against the dashboard's own initiative, like every other id a
    // binding names: one pointing elsewhere resolves to nothing rather than to
    // a name from another initiative.
    if (
      documentQuery.data &&
      documentQuery.data.initiative_id === initiativeId &&
      typeof documentId === "number"
    ) {
      document.set(documentId, documentQuery.data.name);
    }
    return { document, ready: documentId === null || !documentQuery.isLoading };
  }, [scoped, initiativeId, documentId, documentQuery.data, documentQuery.isLoading]);
}
