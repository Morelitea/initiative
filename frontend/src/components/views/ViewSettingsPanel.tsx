import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  TaskSortFieldId,
  type ToolViewWrite,
  type ViewDefinitionInput,
  type ViewLayoutType,
  type ViewSortDirection,
} from "@/api/generated/initiativeAPI.schemas";
import { viewLayouts } from "@/components/projects/projectTasksConfig";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { cardOf, changeAt, columnsOf, nodeAt, pathOf, withCard } from "@/lib/views/draft";
import { type FieldDef, VIEW_NAMESPACES } from "@/lib/views/fields";
import type { ViewNode } from "@/lib/views/tree";
import type { TranslateFn } from "@/types/i18n";

const NO_SORT = "none";

/**
 * The settings of the one thing selected, and only those: the view's own
 * (its name, layout, default and order) on the view, a group's arrangement on
 * a group, and a way to take a field off the card or out of the table.
 */
export const ViewSettingsPanel = ({
  view,
  fields,
  selected,
  onChange,
  onRename,
  onMakeDefault,
  onSelect,
}: {
  view: ToolViewWrite;
  fields: ReadonlyMap<string, FieldDef>;
  selected: string;
  onChange: (definition: ViewDefinitionInput) => void;
  onRename: (name: string) => void;
  onMakeDefault: () => void;
  onSelect: (selected: string) => void;
}) => {
  const { t } = useTranslation(VIEW_NAMESPACES);
  const translate = t as TranslateFn;
  const { definition } = view;

  if (selected === "view") {
    return (
      <ViewSettings
        view={view}
        fields={fields}
        onChange={onChange}
        onRename={onRename}
        onMakeDefault={onMakeDefault}
      />
    );
  }

  if (selected.startsWith("column:")) {
    const ref = selected.slice("column:".length);
    return (
      <Panel heading={translate("viewEditor.column")}>
        <p className="text-muted-foreground text-sm">{translate("viewEditor.columnHelp")}</p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => {
            onChange({
              ...definition,
              columns: columnsOf(definition).filter((each) => each !== ref),
            });
            onSelect("view");
          }}
        >
          {translate("viewEditor.remove")}
        </Button>
      </Panel>
    );
  }

  const card = cardOf(definition);
  const path = pathOf(selected.slice("card:".length));
  const node = nodeAt(card, path);
  if (!node) return <Panel heading={translate("viewEditor.settings")}>{null}</Panel>;
  const change = (next: ViewNode | null) =>
    onChange(
      withCard(
        definition,
        changeAt(card, path, () => next)
      )
    );

  if (node.type === "card") {
    return (
      <Panel heading={translate("viewEditor.card")}>
        <p className="text-muted-foreground text-sm">{translate("viewEditor.cardHelp")}</p>
      </Panel>
    );
  }
  if (node.type === "stack") {
    return <GroupSettings node={node} onChange={change} />;
  }
  const help =
    node.type === "properties"
      ? translate("viewEditor.propertiesHelp")
      : node.type === "plugin"
        ? translate("viewEditor.pluginPartHelp")
        : translate("viewEditor.fieldHelp");
  return (
    <Panel heading={translate("viewEditor.settings")}>
      <p className="text-muted-foreground text-sm">{help}</p>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => {
          change(null);
          onSelect("card:");
        }}
      >
        {translate("viewEditor.remove")}
      </Button>
    </Panel>
  );
};

const Panel = ({ heading, children }: { heading: string; children: React.ReactNode }) => (
  <section className="space-y-4 p-4">
    <h2 className="font-medium text-sm">{heading}</h2>
    {children}
  </section>
);

const ViewSettings = ({
  view,
  fields,
  onChange,
  onRename,
  onMakeDefault,
}: {
  view: ToolViewWrite;
  fields: ReadonlyMap<string, FieldDef>;
  onChange: (definition: ViewDefinitionInput) => void;
  onRename: (name: string) => void;
  onMakeDefault: () => void;
}) => {
  const { t } = useTranslation(VIEW_NAMESPACES);
  const translate = t as TranslateFn;
  const { definition } = view;
  // The name is kept as typed and saved to the view when the field is left,
  // so one rename is one change to undo.
  const [name, setName] = useState(view.name);
  useEffect(() => setName(view.name), [view.name]);
  const commitName = () => {
    const trimmed = name.trim();
    if (trimmed && trimmed !== view.name) onRename(trimmed);
    else setName(view.name);
  };
  const [sort] = definition.sort ?? [];

  return (
    <Panel heading={translate("viewEditor.viewHeading")}>
      <div className="space-y-2">
        <Label htmlFor="view-name">{translate("viewEditor.name")}</Label>
        <Input
          id="view-name"
          value={name}
          maxLength={100}
          onChange={(event) => setName(event.target.value)}
          onBlur={commitName}
          onKeyDown={(event) => {
            if (event.key === "Enter") commitName();
          }}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="view-layout">{translate("viewEditor.layout")}</Label>
        <Select
          value={definition.layout.type}
          onValueChange={(type) =>
            onChange({ ...definition, layout: { type: type as ViewLayoutType } })
          }
        >
          <SelectTrigger id="view-layout">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {Object.entries(viewLayouts).map(([type, layout]) => (
              <SelectItem key={type} value={type}>
                {translate(layout.labelKey)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="flex items-center justify-between gap-2">
        <Label htmlFor="view-default">{translate("viewEditor.default")}</Label>
        <Switch
          id="view-default"
          checked={view.is_default ?? false}
          // The set always opens on one view: choosing another is how this
          // one stops being it.
          disabled={view.is_default ?? false}
          onCheckedChange={(checked) => {
            if (checked) onMakeDefault();
          }}
        />
      </div>
      {definition.layout.type === "table" ? (
        <div className="space-y-2">
          <Label htmlFor="view-sort">{translate("viewEditor.sort")}</Label>
          <Select
            value={sort?.field ?? NO_SORT}
            onValueChange={(field) =>
              onChange({
                ...definition,
                sort:
                  field === NO_SORT
                    ? null
                    : [
                        {
                          field: field as TaskSortFieldId,
                          direction: sort?.direction ?? "asc",
                        },
                      ],
              })
            }
          >
            <SelectTrigger id="view-sort">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_SORT}>{translate("viewEditor.sortNone")}</SelectItem>
              {Object.values(TaskSortFieldId).map((field) => {
                const def = fields.get(field);
                return (
                  <SelectItem key={field} value={field}>
                    {def ? translate(def.label) : field}
                  </SelectItem>
                );
              })}
            </SelectContent>
          </Select>
          {sort ? (
            <Select
              value={sort.direction ?? "asc"}
              onValueChange={(direction) =>
                onChange({
                  ...definition,
                  sort: [{ ...sort, direction: direction as ViewSortDirection }],
                })
              }
            >
              <SelectTrigger aria-label={translate("viewEditor.direction")}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="asc">{translate("viewEditor.ascending")}</SelectItem>
                <SelectItem value="desc">{translate("viewEditor.descending")}</SelectItem>
              </SelectContent>
            </Select>
          ) : null}
        </div>
      ) : null}
    </Panel>
  );
};

/** A group's arrangement, as plain choices. */
const GroupSettings = ({
  node,
  onChange,
}: {
  node: ViewNode;
  onChange: (next: ViewNode | null) => void;
}) => {
  const { t } = useTranslation("projects");
  const props = node.props ?? {};
  const set = (key: string, value: unknown) =>
    onChange({ ...node, props: { ...props, [key]: value === undefined ? undefined : value } });
  const flag = (key: string, label: string) => (
    <div className="flex items-center justify-between gap-2">
      <Label htmlFor={`group-${key}`}>{label}</Label>
      <Switch
        id={`group-${key}`}
        checked={Boolean(props[key])}
        onCheckedChange={(checked) =>
          set(
            key,
            checked ? (key === "align" ? "start" : key === "tone" ? "muted" : true) : undefined
          )
        }
      />
    </div>
  );
  return (
    <Panel heading={t("viewEditor.group")}>
      <div className="space-y-2">
        <Label htmlFor="group-direction">{t("viewEditor.arrange")}</Label>
        <Select
          value={props.direction === "row" ? "row" : "column"}
          onValueChange={(direction) => set("direction", direction === "row" ? "row" : undefined)}
        >
          <SelectTrigger id="group-direction">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="column">{t("viewEditor.stacked")}</SelectItem>
            <SelectItem value="row">{t("viewEditor.sideBySide")}</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div className="space-y-2">
        <Label htmlFor="group-gap">{t("viewEditor.spacing")}</Label>
        <Select
          value={props.gap === "sm" ? "sm" : "xs"}
          onValueChange={(gap) => set("gap", gap === "sm" ? "sm" : undefined)}
        >
          <SelectTrigger id="group-gap">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="xs">{t("viewEditor.tight")}</SelectItem>
            <SelectItem value="sm">{t("viewEditor.roomy")}</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {props.direction === "row" ? flag("wrap", t("viewEditor.wrap")) : null}
      {flag("align", t("viewEditor.ownWidth"))}
      {flag("tone", t("viewEditor.muted"))}
    </Panel>
  );
};
