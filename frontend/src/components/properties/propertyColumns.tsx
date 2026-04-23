import type { ColumnDef } from "@tanstack/react-table";

import type {
  PropertyDefinitionRead,
  PropertySummary,
} from "@/api/generated/initiativeAPI.schemas";

import { PropertyValueCell } from "./PropertyValueCell";
import { iconForPropertyType } from "./propertyTypeIcons";

/**
 * Upper bound on the number of property columns appended to a table. Large
 * guilds could in theory define many more; beyond this the column visibility
 * dropdown becomes unmanageable and TanStack has to keep visibility state
 * for every one. Extra definitions are silently dropped with a console
 * warning — the manager page is still the place to see them all.
 */
const PROPERTY_COLUMN_CAP = 100;

/**
 * Column id for a property. Defaults to the property's name so the column
 * visibility dropdown (which uses the column id as its label) shows a
 * human-readable label. Falls back to ``property-<id>`` when the name is
 * empty so the id is always a stable, non-blank string.
 *
 * When the caller has already detected a name collision (two definitions
 * with the same name in the same list — only possible in global views that
 * union across initiatives), pass ``isAmbiguous=true`` and the id is
 * suffixed with the property id to stay unique + stable.
 */
export const propertyColumnId = (
  definition: Pick<PropertyDefinitionRead, "id" | "name">,
  isAmbiguous = false
): string => {
  const trimmed = definition.name?.trim();
  const base = trimmed && trimmed.length > 0 ? trimmed : `property-${definition.id}`;
  return isAmbiguous ? `${base} (#${definition.id})` : base;
};

/**
 * Pre-compute which definitions share a trimmed, case-insensitive name so
 * ``propertyColumnId`` can disambiguate them. Names that appear only once
 * keep the plain form; duplicates get the ``(#<id>)`` suffix.
 */
const buildAmbiguousNameSet = (definitions: PropertyDefinitionRead[]): Set<string> => {
  const counts = new Map<string, number>();
  for (const definition of definitions) {
    const trimmed = definition.name?.trim()?.toLowerCase();
    if (!trimmed) continue;
    counts.set(trimmed, (counts.get(trimmed) ?? 0) + 1);
  }
  const ambiguous = new Set<string>();
  for (const [key, value] of counts.entries()) {
    if (value > 1) ambiguous.add(key);
  }
  return ambiguous;
};

const isDefinitionAmbiguous = (
  definition: Pick<PropertyDefinitionRead, "name">,
  ambiguousNames: Set<string>
): boolean => {
  const trimmed = definition.name?.trim()?.toLowerCase();
  if (!trimmed) return false;
  return ambiguousNames.has(trimmed);
};

/**
 * Build a TanStack ``ColumnDef`` per property definition. Each column is
 * hidden by default (callers are expected to seed ``columnVisibility``);
 * ``enableSorting`` is off because sort across heterogeneous typed columns
 * needs server support we don't have yet.
 */
export function buildPropertyColumns<T>(
  definitions: PropertyDefinitionRead[],
  getProperties: (row: T) => PropertySummary[] | undefined | null
): ColumnDef<T>[] {
  if (definitions.length > PROPERTY_COLUMN_CAP) {
    console.warn(
      `[propertyColumns] capping at ${PROPERTY_COLUMN_CAP} columns (saw ${definitions.length})`
    );
  }
  const capped = definitions.slice(0, PROPERTY_COLUMN_CAP);
  const ambiguousNames = buildAmbiguousNameSet(capped);
  return capped.map((definition) => {
    const Icon = iconForPropertyType(definition.type);
    const ambiguous = isDefinitionAmbiguous(definition, ambiguousNames);
    return {
      id: propertyColumnId(definition, ambiguous),
      header: () => (
        <span className="text-muted-foreground inline-flex items-center gap-1.5 text-xs font-medium">
          <Icon className="h-3.5 w-3.5" aria-hidden />
          <span className="truncate">
            {ambiguous ? `${definition.name} (#${definition.id})` : definition.name}
          </span>
        </span>
      ),
      cell: ({ row }) => {
        const rowValue = row.original as T;
        const summaries = getProperties(rowValue) ?? [];
        const summary = summaries.find((s) => s.property_id === definition.id);
        return <PropertyValueCell summary={summary} variant="cell" />;
      },
      enableHiding: true,
      enableSorting: false,
      size: 160,
    } satisfies ColumnDef<T>;
  });
}

/** Default-hidden visibility map for a property-column list. */
export const propertyColumnsHidden = (
  definitions: PropertyDefinitionRead[]
): Record<string, boolean> => {
  const result: Record<string, boolean> = {};
  const ambiguousNames = buildAmbiguousNameSet(definitions);
  for (const definition of definitions) {
    const ambiguous = isDefinitionAmbiguous(definition, ambiguousNames);
    result[propertyColumnId(definition, ambiguous)] = false;
  }
  return result;
};

/**
 * Resolve the full set of column ids that ``buildPropertyColumns`` would
 * generate for the same definitions list, with duplicate names disambiguated
 * via the ``(#<id>)`` suffix. Callers use this to seed TanStack Table's
 * ``columnVisibility`` map so the default-hidden toggle keys match the
 * column ids actually rendered.
 */
export const propertyColumnIds = (definitions: PropertyDefinitionRead[]): string[] => {
  const ambiguousNames = buildAmbiguousNameSet(definitions);
  return definitions.map((definition) =>
    propertyColumnId(definition, isDefinitionAmbiguous(definition, ambiguousNames))
  );
};
