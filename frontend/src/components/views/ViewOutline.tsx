import {
  DndContext,
  type DragEndEvent,
  KeyboardSensor,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { EyeOff, GripVertical, LayoutList, Plus } from "lucide-react";
import { type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ToolViewWrite } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import {
  addableFields,
  cardOf,
  columnsOf,
  type NodePath,
  pathKey,
  pathOf,
  removable,
  type Selection,
  sameSelection,
  showsAllProperties,
} from "@/lib/views/draft";
import { type FieldDef, VIEW_NAMESPACES } from "@/lib/views/fields";
import type { PluginOnItems } from "@/lib/views/plugins";
import type { ViewNode } from "@/lib/views/tree";
import { localized } from "@/lib/widgets/widgetMeta";
import type { TranslateFn } from "@/types/i18n";

import type { ViewEdits } from "./ViewEditor";

/** A plug-in as the picker offers it: its name, and its parts by theirs. */
type PickerPlugin = {
  id: number;
  name: string;
  parts: { id: string; name: string; description?: string }[];
};

const parentKey = (key: string) => pathKey(pathOf(key).slice(0, -1));

/**
 * What the view is made of, as a list beside the canvas: the view itself,
 * then a board's card part by part or a table's columns in order. A row is
 * dragged to move it among its siblings, hidden from its own row, and
 * selected to change it. Add offers what is not there yet, under where it
 * comes from.
 */
export const ViewOutline = ({
  view,
  fields,
  plugins,
  selection,
  edits,
  locked,
}: {
  view: ToolViewWrite;
  fields: ReadonlyMap<string, FieldDef>;
  plugins: ReadonlyMap<number, PluginOnItems>;
  selection: Selection;
  edits: ViewEdits;
  /** A save is under way, and nothing changes until it answers. */
  locked: boolean;
}) => {
  const { t, i18n } = useTranslation(VIEW_NAMESPACES);
  const translate = t as TranslateFn;
  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 4 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 200, tolerance: 8 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );
  const { definition } = view;
  const layout = definition.layout.type;
  const card = cardOf(definition);
  const columns = columnsOf(definition);
  const offeredPlugins: PickerPlugin[] = [...plugins.values()].map((plugin) => ({
    id: plugin.id,
    name: plugin.name,
    parts: [...plugin.parts.values()].map((part) => ({
      id: part.id,
      name: localized(part.name, i18n.language) ?? part.id,
      description: localized(part.description, i18n.language),
    })),
  }));

  const labelOf = (field: FieldDef) =>
    field.source === "builtin" ? translate(field.label) : field.label;
  const partLabel = (node: ViewNode): string => {
    switch (node.type) {
      case "card":
        return translate("viewEditor.card");
      case "stack":
        return node.props?.direction === "row"
          ? translate("viewEditor.row")
          : translate("viewEditor.group");
      case "properties":
        return translate("viewEditor.allProperties");
      case "plugin": {
        const plugin = offeredPlugins.find((each) => each.id === Number(node.props?.plugin));
        const part = plugin?.parts.find((each) => each.id === node.props?.part);
        return part?.name ?? translate("viewEditor.missingPart");
      }
      case "field": {
        const field = fields.get(String(node.props?.field));
        return field ? labelOf(field) : translate("viewEditor.missingField");
      }
      default:
        return node.type;
    }
  };
  const isSelected = (other: Selection) => sameSelection(selection, other);

  const onCardDragEnd = ({ active, over }: DragEndEvent) => {
    const from = String(active.id);
    const to = over ? String(over.id) : null;
    // A part moves among its own siblings.
    if (!to || from === to || parentKey(from) !== parentKey(to)) return;
    edits.movePart(pathOf(from).slice(0, -1), pathOf(from).at(-1) ?? 0, pathOf(to).at(-1) ?? 0);
  };
  const onColumnDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    edits.moveColumn(columns.indexOf(String(active.id)), columns.indexOf(String(over.id)));
  };

  const partRows = (parent: ViewNode, parentPath: NodePath, depth: number): ReactNode => {
    const children = parent.children ?? [];
    const keys = children.map((_, index) => pathKey([...parentPath, index]));
    return (
      <SortableContext items={keys} strategy={verticalListSortingStrategy}>
        {children.map((child, index) => {
          const path = [...parentPath, index];
          return (
            <div key={keys[index]}>
              <OutlineRow
                id={keys[index]}
                depth={depth}
                label={partLabel(child)}
                selected={isSelected({ kind: "part", path })}
                onSelect={() => edits.select({ kind: "part", path })}
                onHide={removable(child, fields) ? () => edits.removePart(path) : undefined}
                locked={locked}
              />
              {child.children ? partRows(child, path, depth + 1) : null}
            </div>
          );
        })}
      </SortableContext>
    );
  };

  return (
    <nav aria-label={translate("viewEditor.outline")} className="flex h-full flex-col">
      <div className="flex-1 space-y-1 overflow-y-auto p-3">
        <OutlineRow
          id="view"
          depth={0}
          label={view.name}
          icon={<LayoutList className="h-4 w-4" aria-hidden="true" />}
          selected={isSelected({ kind: "view" })}
          onSelect={() => edits.select({ kind: "view" })}
          fixed
        />
        {layout === "board" ? (
          <DndContext sensors={sensors} onDragEnd={onCardDragEnd}>
            <OutlineRow
              id="card"
              depth={1}
              label={partLabel(card)}
              selected={isSelected({ kind: "part", path: [] })}
              onSelect={() => edits.select({ kind: "part", path: [] })}
              fixed
            />
            {partRows(card, [], 2)}
          </DndContext>
        ) : null}
        {layout === "table" ? (
          <DndContext sensors={sensors} onDragEnd={onColumnDragEnd}>
            <p className="px-2 pt-2 font-medium text-muted-foreground text-xs">
              {translate("viewEditor.columns")}
            </p>
            <SortableContext items={columns} strategy={verticalListSortingStrategy}>
              {columns.map((id) => {
                const field = fields.get(id);
                return (
                  <OutlineRow
                    key={id}
                    id={id}
                    depth={1}
                    label={field ? labelOf(field) : translate("viewEditor.missingField")}
                    selected={isSelected({ kind: "column", field: id })}
                    onSelect={() => edits.select({ kind: "column", field: id })}
                    // A table always has its title.
                    onHide={field?.hideable === false ? undefined : () => edits.removeColumn(id)}
                    locked={locked}
                  />
                );
              })}
            </SortableContext>
          </DndContext>
        ) : null}
      </div>
      {layout === "calendar" ? null : (
        <div className="border-t p-3">
          <AddPicker
            fields={addableFields(definition, fields)}
            labelOf={labelOf}
            onField={(field) =>
              layout === "board"
                ? edits.addPart({ type: "field", props: { field: field.id } })
                : edits.addColumn(field.id)
            }
            plugins={offeredPlugins}
            // A table draws fields only; a card takes parts as well.
            withParts={layout === "board"}
            onPart={(plugin, part) => edits.addPart({ type: "plugin", props: { plugin, part } })}
            layoutParts={
              layout === "board"
                ? [
                    {
                      label: translate("viewEditor.group"),
                      node: { type: "stack", props: { align: "start" }, children: [] },
                    },
                    ...(showsAllProperties(card)
                      ? []
                      : [
                          {
                            label: translate("viewEditor.allProperties"),
                            node: { type: "properties" },
                          },
                        ]),
                  ]
                : []
            }
            onLayout={edits.addPart}
            locked={locked}
          />
        </div>
      )}
    </nav>
  );
};

const OutlineRow = ({
  id,
  depth,
  label,
  icon,
  selected,
  onSelect,
  onHide,
  fixed = false,
  locked = false,
}: {
  id: string;
  depth: number;
  label: string;
  icon?: ReactNode;
  selected: boolean;
  onSelect: () => void;
  /** Absent: the row cannot be hidden. */
  onHide?: () => void;
  /** It has no place to move to. */
  fixed?: boolean;
  locked?: boolean;
}) => {
  const { t } = useTranslation("projects");
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id,
    disabled: fixed || locked,
  });
  return (
    <div
      ref={fixed ? undefined : setNodeRef}
      style={fixed ? undefined : { transform: CSS.Transform.toString(transform), transition }}
      className={cn(
        "group flex items-center gap-1 rounded-md pr-1 text-sm",
        selected ? "bg-accent text-accent-foreground" : "hover:bg-muted",
        isDragging && "opacity-60"
      )}
    >
      <span aria-hidden="true" style={{ width: `${depth * 0.75}rem` }} className="shrink-0" />
      {fixed ? (
        <span className="flex h-7 w-6 items-center justify-center text-muted-foreground">
          {icon}
        </span>
      ) : (
        <button
          type="button"
          className="flex h-7 w-6 cursor-grab items-center justify-center text-muted-foreground disabled:cursor-not-allowed"
          aria-label={t("viewEditor.move", { name: label })}
          disabled={locked}
          {...attributes}
          {...listeners}
        >
          <GripVertical className="h-4 w-4" />
        </button>
      )}
      <button
        type="button"
        className="min-w-0 flex-1 truncate py-1 text-left"
        aria-pressed={selected}
        onClick={onSelect}
      >
        {label}
      </button>
      {onHide ? (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-7 w-7 opacity-0 focus-visible:opacity-100 group-hover:opacity-100"
          aria-label={t("viewEditor.hide", { name: label })}
          disabled={locked}
          onClick={onHide}
        >
          <EyeOff className="h-4 w-4" />
        </Button>
      ) : null}
    </div>
  );
};

type PickerGroupEntry = {
  key: string;
  heading: string;
  fields: FieldDef[];
  plugin: number;
  parts: PickerPlugin["parts"];
};

/** What can be added, shown as things rather than ids: fields by where they
 *  come from, each plug-in's fields and parts under its name, and the layout
 *  parts. */
const AddPicker = ({
  fields,
  labelOf,
  onField,
  plugins,
  withParts,
  onPart,
  layoutParts,
  onLayout,
  locked,
}: {
  fields: FieldDef[];
  labelOf: (field: FieldDef) => string;
  onField: (field: FieldDef) => void;
  plugins: PickerPlugin[];
  withParts: boolean;
  onPart: (plugin: number, part: string) => void;
  layoutParts: { label: string; node: ViewNode }[];
  onLayout: (node: ViewNode) => void;
  locked: boolean;
}) => {
  const { t } = useTranslation("projects");
  const [open, setOpen] = useState(false);
  const groups: PickerGroupEntry[] = [
    {
      key: "builtin",
      heading: t("viewEditor.builtIn"),
      fields: fields.filter((field) => field.source === "builtin"),
      plugin: 0,
      parts: [],
    },
    {
      key: "properties",
      heading: t("viewEditor.properties"),
      fields: fields.filter((field) => field.source === "property"),
      plugin: 0,
      parts: [],
    },
    ...plugins.map((plugin) => ({
      key: `plugin:${plugin.id}`,
      heading: plugin.name,
      fields: fields.filter((field) => field.plugin?.install === plugin.id),
      plugin: plugin.id,
      parts: withParts ? plugin.parts : [],
    })),
  ].filter((group) => group.fields.length > 0 || group.parts.length > 0);
  const pick = (run: () => void) => {
    run();
    setOpen(false);
  };
  const nothing = groups.length === 0 && layoutParts.length === 0;
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="w-full"
          disabled={nothing || locked}
        >
          <Plus className="h-4 w-4" />
          {t("viewEditor.add")}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="max-h-96 w-72 overflow-y-auto p-2">
        {groups.map((group) => (
          <PickerGroup key={group.key} heading={group.heading}>
            {group.fields.map((field) => {
              const Icon = field.icon;
              return (
                <PickerItem key={field.id} onClick={() => pick(() => onField(field))}>
                  {Icon ? (
                    <Icon className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                  ) : null}
                  {labelOf(field)}
                </PickerItem>
              );
            })}
            {group.parts.map((part) => (
              <PickerItem
                key={`part:${part.id}`}
                description={part.description}
                onClick={() => pick(() => onPart(group.plugin, part.id))}
              >
                {part.name}
              </PickerItem>
            ))}
          </PickerGroup>
        ))}
        {layoutParts.length > 0 ? (
          <PickerGroup heading={t("viewEditor.layoutParts")}>
            {layoutParts.map((part) => (
              <PickerItem key={part.label} onClick={() => pick(() => onLayout(part.node))}>
                {part.label}
              </PickerItem>
            ))}
          </PickerGroup>
        ) : null}
      </PopoverContent>
    </Popover>
  );
};

const PickerGroup = ({ heading, children }: { heading: string; children: ReactNode }) => (
  <div className="py-1">
    <p className="px-2 pb-1 font-medium text-muted-foreground text-xs">{heading}</p>
    {children}
  </div>
);

const PickerItem = ({
  description,
  onClick,
  children,
}: {
  description?: string;
  onClick: () => void;
  children: ReactNode;
}) => (
  <button
    type="button"
    className="flex w-full flex-col items-start rounded-sm px-2 py-1.5 text-left text-sm hover:bg-muted focus-visible:bg-muted focus-visible:outline-none"
    onClick={onClick}
  >
    <span className="flex items-center gap-2">{children}</span>
    {description ? <span className="text-muted-foreground text-xs">{description}</span> : null}
  </button>
);
