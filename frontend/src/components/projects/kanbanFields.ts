import type { PropertyDefinitionRead } from "@/api/generated/initiativeAPI.schemas";
import { propertyColumnId, propertyColumnLabel } from "@/components/properties/propertyColumns";

/**
 * What a kanban card is allowed to show, and what a reader may turn off.
 *
 * The table calls these "columns" because they are columns. On a board there
 * is no column to hide — the columns are the statuses — so the same idea is
 * called **fields**, and this list is what the Fields menu offers.
 *
 * The title is deliberately absent: a card with no title is not a card.
 */
export const KANBAN_FIELD_IDS = [
  "description",
  "assignees",
  "startDate",
  "dueDate",
  "recurrence",
  "checklist",
  "priority",
  "comments",
  "blockers",
  "tags",
] as const;

export type KanbanFieldId = (typeof KANBAN_FIELD_IDS)[number];

/** i18n key per field, in the `projects` namespace. */
export const KANBAN_FIELD_LABEL_KEYS: Record<KanbanFieldId, string> = {
  description: "kanban.fields.description",
  assignees: "kanban.fields.assignees",
  startDate: "kanban.fields.startDate",
  dueDate: "kanban.fields.dueDate",
  recurrence: "kanban.fields.recurrence",
  checklist: "kanban.fields.checklist",
  priority: "kanban.fields.priority",
  comments: "kanban.fields.comments",
  blockers: "kanban.fields.blockers",
  tags: "kanban.fields.tags",
};

/**
 * Which fields are off, keyed by field id — the same shape TanStack uses for
 * column visibility, so `usePersistedColumnVisibility` stores it as-is.
 *
 * **Absent means shown.** A card that has never been configured shows
 * everything it has, which is what it did before this menu existed, and a
 * field added in a later release appears without anybody re-enabling it.
 */
export type KanbanFieldVisibility = Record<string, boolean>;

/** Whether a field should be rendered. Anything not explicitly off is on. */
export const isKanbanFieldVisible = (visibility: KanbanFieldVisibility, field: string): boolean =>
  visibility[field] !== false;

/** Where a project's choices live. Per project, because the fields that earn
 *  their place on a card differ from one board to the next. */
export const kanbanFieldsStorageKey = (projectId: number): string =>
  `initiative-project-${projectId}-kanban-fields`;

export type KanbanFieldOption = { id: string; label: string; definitionId?: number };

/**
 * The menu's contents: the built-in fields followed by one entry per property
 * defined on the initiative.
 *
 * Property ids come from `propertyColumnId`, the same function the table's
 * column list uses, so a property is named identically in both menus and two
 * properties sharing a name stay told apart.
 */
export const kanbanFieldOptions = (
  definitions: PropertyDefinitionRead[],
  translate: (key: string) => string
): KanbanFieldOption[] => [
  ...KANBAN_FIELD_IDS.map((id) => ({ id, label: translate(KANBAN_FIELD_LABEL_KEYS[id]) })),
  ...propertyFieldOptions(definitions),
];

/**
 * The two questions a card asks, answered once per change of choice rather
 * than once per card.
 *
 * `showsProperty` takes the property's **id**, not its name: whether a
 * property's menu entry carries a `(#id)` suffix depends on the whole
 * definition list, which a single card never sees. Resolving that here, where
 * the list is in hand, is what keeps two same-named properties independently
 * toggleable.
 */
export type KanbanCardFields = {
  shows: (field: KanbanFieldId) => boolean;
  showsProperty: (propertyId: number) => boolean;
};

export const buildKanbanCardFields = (
  visibility: KanbanFieldVisibility,
  definitions: PropertyDefinitionRead[]
): KanbanCardFields => {
  const hiddenProperties = new Set<number>();
  for (const option of propertyFieldOptions(definitions)) {
    if (option.definitionId !== undefined && visibility[option.id] === false) {
      hiddenProperties.add(option.definitionId);
    }
  }
  return {
    shows: (field) => isKanbanFieldVisible(visibility, field),
    showsProperty: (propertyId) => !hiddenProperties.has(propertyId),
  };
};

const propertyFieldOptions = (definitions: PropertyDefinitionRead[]): KanbanFieldOption[] => {
  const ambiguous = ambiguousNames(definitions);
  return definitions.map((definition) => {
    const isAmbiguous = hasAmbiguousName(definition, ambiguous);
    return {
      id: propertyColumnId(definition, isAmbiguous),
      label: propertyColumnLabel(definition, isAmbiguous),
      definitionId: definition.id,
    };
  });
};

// Mirrors the disambiguation in `propertyColumns`, which keeps its own copy
// private. Two properties with one name have to stay distinguishable here too,
// or turning one off would turn both off.
const ambiguousNames = (definitions: PropertyDefinitionRead[]): Set<string> => {
  const counts = new Map<string, number>();
  for (const definition of definitions) {
    const name = definition.name?.trim()?.toLowerCase();
    if (!name) continue;
    counts.set(name, (counts.get(name) ?? 0) + 1);
  }
  return new Set([...counts].filter(([, count]) => count > 1).map(([name]) => name));
};

const hasAmbiguousName = (
  definition: Pick<PropertyDefinitionRead, "name">,
  ambiguous: Set<string>
): boolean => {
  const name = definition.name?.trim()?.toLowerCase();
  return name ? ambiguous.has(name) : false;
};
