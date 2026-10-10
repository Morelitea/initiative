import type {
  DetailLayoutRead,
  DetailLayoutWrite,
  ListLayoutRead,
  ListLayoutReadKind,
  ListLayoutWrite,
  ToolLayoutSetRead,
} from "@/api/generated/initiativeAPI.schemas";

/** When a layout built here was last changed. */
const CHANGED = "2026-10-01T12:00:00.000Z";

/** A project's layouts as the server reads them until it changes any: its
 *  table (which it opens on), board and calendar, then the task's detail,
 *  each as shipped. `layouts` replaces those of the same kind. */
export function buildToolLayoutSet(
  overrides: Partial<Omit<ToolLayoutSetRead, "layouts">> & {
    layouts?: (ListLayoutRead | DetailLayoutRead)[];
  } = {}
): ToolLayoutSetRead {
  const { layouts = [], ...rest } = overrides;
  const shipped: (ListLayoutRead | DetailLayoutRead)[] = [
    ...(["table", "board", "calendar"] as ListLayoutReadKind[]).map((kind) => ({
      kind,
      is_default: kind === "table",
      definition: {},
      updated_at: null,
    })),
    { kind: "task", definition: {}, updated_at: null },
  ];
  return {
    layouts: shipped.map((each) => layouts.find((layout) => layout.kind === each.kind) ?? each),
    can_configure: true,
    ...rest,
  };
}

/** `set` as the server answers a change: `write` saved, and dated. */
export function buildSavedLayoutSet(
  set: ToolLayoutSetRead,
  write: ListLayoutWrite | DetailLayoutWrite
): ToolLayoutSetRead {
  return {
    ...set,
    layouts: set.layouts.map((layout) =>
      layout.kind === write.kind
        ? ({ ...layout, definition: write.definition, updated_at: CHANGED } as typeof layout)
        : layout
    ),
  };
}
