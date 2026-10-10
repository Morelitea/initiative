import { type ReactNode, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  TaskSortFieldId,
  type ToolViewWrite,
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
import { cardOf, nodeAt, removable, type Selection } from "@/lib/views/draft";
import { type FieldDef, VIEW_NAMESPACES } from "@/lib/views/fields";
import type { ViewNode } from "@/lib/views/tree";
import type { TranslateFn } from "@/types/i18n";

import type { ViewEdits } from "./ViewEditor";

const NO_SORT = "none";

/**
 * The settings of the one thing selected, and only those: the view's own
 * (its name, layout, default and order) on the view, a group's arrangement on
 * a group, and a way to take a part off the card or a column out of the
 * table, where it may go.
 */
export const ViewSettingsPanel = ({
  view,
  fields,
  selection,
  edits,
  locked,
}: {
  view: ToolViewWrite;
  fields: ReadonlyMap<string, FieldDef>;
  selection: Selection;
  edits: ViewEdits;
  /** A save is under way, and nothing changes until it answers. */
  locked: boolean;
}) => (
  // Disabled as one, so a save under way leaves every control as it was.
  <fieldset disabled={locked} className="min-w-0">
    <SelectedSettings view={view} fields={fields} selection={selection} edits={edits} />
  </fieldset>
);

const SelectedSettings = ({
  view,
  fields,
  selection,
  edits,
}: {
  view: ToolViewWrite;
  fields: ReadonlyMap<string, FieldDef>;
  selection: Selection;
  edits: ViewEdits;
}) => {
  const { t } = useTranslation(VIEW_NAMESPACES);
  const translate = t as TranslateFn;

  if (selection.kind === "view") {
    return <ViewSettings view={view} fields={fields} edits={edits} />;
  }

  if (selection.kind === "column") {
    const keeps = fields.get(selection.field)?.hideable === false;
    return (
      <Panel heading={translate("viewEditor.column")}>
        <p className="text-muted-foreground text-sm">
          {translate(keeps ? "viewEditor.titleHelp" : "viewEditor.columnHelp")}
        </p>
        {keeps ? null : (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => edits.removeColumn(selection.field)}
          >
            {translate("viewEditor.remove")}
          </Button>
        )}
      </Panel>
    );
  }

  const node = nodeAt(cardOf(view.definition), selection.path);
  if (!node) return null;
  if (node.type === "card") {
    return (
      <Panel heading={translate("viewEditor.card")}>
        <p className="text-muted-foreground text-sm">{translate("viewEditor.cardHelp")}</p>
      </Panel>
    );
  }
  const canRemove = removable(node, fields);
  const remove = canRemove ? (
    <Button
      type="button"
      variant="outline"
      size="sm"
      onClick={() => edits.removePart(selection.path)}
    >
      {translate("viewEditor.remove")}
    </Button>
  ) : null;

  if (node.type === "stack") {
    return (
      <GroupSettings node={node} onChange={(next) => edits.changePart(selection.path, next)}>
        {remove ?? (
          <p className="text-muted-foreground text-xs">{translate("viewEditor.holdsTitle")}</p>
        )}
      </GroupSettings>
    );
  }
  const help =
    node.type === "properties"
      ? "viewEditor.propertiesHelp"
      : node.type === "plugin"
        ? "viewEditor.pluginPartHelp"
        : canRemove
          ? "viewEditor.fieldHelp"
          : "viewEditor.titleHelp";
  return (
    <Panel heading={translate("viewEditor.settings")}>
      <p className="text-muted-foreground text-sm">{translate(help)}</p>
      {remove}
    </Panel>
  );
};

const Panel = ({ heading, children }: { heading: string; children: ReactNode }) => (
  <section className="space-y-4 p-4">
    <h2 className="font-medium text-sm">{heading}</h2>
    {children}
  </section>
);

const ViewSettings = ({
  view,
  fields,
  edits,
}: {
  view: ToolViewWrite;
  fields: ReadonlyMap<string, FieldDef>;
  edits: ViewEdits;
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
    if (trimmed && trimmed !== view.name) edits.rename(trimmed);
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
            edits.setDefinition({ ...definition, layout: { type: type as ViewLayoutType } })
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
            if (checked) edits.makeDefault();
          }}
        />
      </div>
      {definition.layout.type === "table" ? (
        <div className="space-y-2">
          <Label htmlFor="view-sort">{translate("viewEditor.sort")}</Label>
          <Select
            value={sort?.field ?? NO_SORT}
            onValueChange={(field) =>
              edits.setDefinition({
                ...definition,
                sort:
                  field === NO_SORT
                    ? null
                    : [{ field: field as TaskSortFieldId, direction: sort?.direction ?? "asc" }],
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
                edits.setDefinition({
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

/** A group's arrangement, as plain choices. Each sets one prop, and the
 *  group's default is the prop left out. */
const GroupSettings = ({
  node,
  onChange,
  children,
}: {
  node: ViewNode;
  onChange: (next: ViewNode) => void;
  children: ReactNode;
}) => {
  const { t } = useTranslation("projects");
  const props = node.props ?? {};
  const set = (key: string, value: unknown) => {
    const { [key]: _left, ...rest } = props;
    onChange({ ...node, props: value === undefined ? rest : { ...rest, [key]: value } });
  };
  const flag = (key: string, on: unknown, label: string) => (
    <div className="flex items-center justify-between gap-2">
      <Label htmlFor={`group-${key}`}>{label}</Label>
      <Switch
        id={`group-${key}`}
        checked={props[key] === on}
        onCheckedChange={(checked) => set(key, checked ? on : undefined)}
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
      {props.direction === "row" ? flag("wrap", true, t("viewEditor.wrap")) : null}
      {flag("align", "start", t("viewEditor.ownWidth"))}
      {flag("tone", "muted", t("viewEditor.muted"))}
      {children}
    </Panel>
  );
};
