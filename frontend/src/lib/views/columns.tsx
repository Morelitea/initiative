import { PropertyColumnHeader } from "@/components/properties/propertyColumns";
import { SortHeader } from "@/components/SortIcon";
import type { AppColumnDef } from "@/lib/table";

import { FIELD_RENDERERS, type FieldDef, type ViewEnv, type ViewItem } from "./fields";

export type FieldColumnOptions<T extends ViewItem> = Pick<
  AppColumnDef<T>,
  "sortFn" | "sortUndefined" | "size" | "cell"
> & {
  /** The id a table gave the column before the field had one: stored
   *  visibility, grouping and sorting are keyed by it. */
  id?: string;
  /** What the column sorts by, where that is not the field's value. */
  sortBy?: (item: T) => unknown;
};

/**
 * A field as a table column: the field's id, its label as the header, and its
 * renderer's cell. It sorts only when given a `sortFn`.
 */
export const fieldColumn = <T extends ViewItem>(
  field: FieldDef,
  env: ViewEnv,
  { id = field.id, sortBy = field.value, ...column }: FieldColumnOptions<T> = {}
): AppColumnDef<T> => {
  const Renderer = FIELD_RENDERERS[field.kind];
  const label = field.source === "builtin" ? env.t(field.label) : field.label;
  const sortable = column.sortFn !== undefined;
  return {
    id,
    accessorFn: sortBy,
    header: ({ column: tableColumn }) => {
      if (field.source === "property") {
        return <PropertyColumnHeader icon={field.icon} label={label} />;
      }
      if (!sortable) return <span className="font-medium">{label}</span>;
      // A date's header is as wide as its cells.
      return (
        <SortHeader
          column={tableColumn}
          label={label}
          className={field.kind === "date" ? "min-w-30" : undefined}
        />
      );
    },
    cell: ({ row }) => (
      <Renderer
        value={field.value(row.original)}
        item={row.original}
        field={field}
        variant="cell"
        env={env}
      />
    ),
    enableSorting: sortable,
    enableHiding: field.hideable,
    // What the Columns menu calls it, rather than its id.
    meta: { label },
    ...column,
  };
};
