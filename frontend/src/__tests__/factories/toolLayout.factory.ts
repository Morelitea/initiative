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

/** A target's layouts as the server reads them until it changes any, each as
 *  shipped: a project's table (which it opens on), board and calendar, then
 *  its task's detail; or, with `tool: "calendar"`, the initiative calendar's
 *  calendar and its event's detail. `layouts` replaces those of the same
 *  kind. */
export function buildToolLayoutSet(
  overrides: Partial<Omit<ToolLayoutSetRead, "layouts">> & {
    layouts?: (ListLayoutRead | DetailLayoutRead)[];
    tool?: "project" | "calendar";
  } = {}
): ToolLayoutSetRead {
  const { layouts = [], tool = "project", ...rest } = overrides;
  const lists: ListLayoutReadKind[] =
    tool === "project" ? ["table", "board", "calendar"] : ["calendar"];
  const shipped: (ListLayoutRead | DetailLayoutRead)[] = [
    ...lists.map((kind, index) => ({
      kind,
      is_default: index === 0,
      definition: {},
      updated_at: null,
    })),
    { kind: tool === "project" ? "task" : "calendar_event", definition: {}, updated_at: null },
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
