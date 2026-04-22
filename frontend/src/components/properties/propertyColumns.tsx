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
 */
export const propertyColumnId = (
  definition: Pick<PropertyDefinitionRead, "id" | "name">
): string => {
  const trimmed = definition.name?.trim();
  return trimmed && trimmed.length > 0 ? trimmed : `property-${definition.id}`;
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
  return capped.map((definition) => {
    const Icon = iconForPropertyType(definition.type);
    return {
      id: propertyColumnId(definition),
      header: () => (
        <span className="text-muted-foreground inline-flex items-center gap-1.5 text-xs font-medium">
          <Icon className="h-3.5 w-3.5" aria-hidden />
          <span className="truncate">{definition.name}</span>
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
  for (const definition of definitions) {
    result[propertyColumnId(definition)] = false;
  }
  return result;
};
