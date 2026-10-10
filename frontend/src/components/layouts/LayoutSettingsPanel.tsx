import { type ReactNode, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { TaskStatusRead } from "@/api/generated/initiativeAPI.schemas";
import { listLayoutLooks } from "@/components/projects/projectTasksConfig";
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
import { LAYOUT_REGIONS } from "@/lib/layouts/detailLayout";
import {
  cardOf,
  type ListLayout,
  MAX_TITLE_LENGTH,
  type NodePath,
  nodeAt,
  removable,
  type Selection,
} from "@/lib/layouts/draft";
import { type FieldDef, LAYOUT_NAMESPACES } from "@/lib/layouts/fields";
import { TASK_LAYOUT } from "@/lib/layouts/tasks";
import type { LayoutNode } from "@/lib/layouts/tree";
import type { TranslateFn } from "@/types/i18n";

import type { LayoutEdits } from "./LayoutEditor";

/**
 * The settings of the one thing selected, and only those: the list layout's
 * own (whether the project opens on it, and putting it back as shipped) on the
 * layout, a group's arrangement on a group, and a way to take a part off the
 * card or a column out of the table, where it may go.
 */
export const ListLayoutSettings = ({
  layout,
  opensFirst,
  stored,
  fields,
  selection,
  edits,
  locked,
}: {
  layout: ListLayout;
  /** Whether the project opens on it. */
  opensFirst: boolean;
  /** Whether the project changed it, as against drawing it as shipped. */
  stored: boolean;
  fields: ReadonlyMap<string, FieldDef>;
  selection: Selection;
  edits: LayoutEdits;
  /** A save is under way, and nothing changes until it answers. */
  locked: boolean;
}) => {
  const { t } = useTranslation(LAYOUT_NAMESPACES);
  const translate = t as TranslateFn;
  return (
    // Disabled as one, so a save under way leaves every control as it was.
    <fieldset disabled={locked} className="min-w-0">
      {selection.kind === "layout" ? (
        <Panel heading={translate(listLayoutLooks[layout.kind].labelKey)}>
          <p className="text-muted-foreground text-sm">
            {translate(`layoutEditor.listHelp.${layout.kind}`)}
          </p>
          <div className="flex items-center justify-between gap-2">
            <Label htmlFor="layout-default">{translate("layoutEditor.opensFirst")}</Label>
            <Switch
              id="layout-default"
              checked={opensFirst}
              // The project always opens on one list: choosing another is how
              // this one stops being it.
              disabled={opensFirst}
              onCheckedChange={(checked) => {
                if (checked) edits.makeDefault();
              }}
            />
          </div>
          <Shipped stored={stored} edits={edits} />
        </Panel>
      ) : selection.kind === "column" ? (
        <ColumnSettings field={selection.field} fields={fields} edits={edits} />
      ) : (
        <PartSettings
          tree={cardOf(layout.definition)}
          path={selection.path}
          fields={fields}
          edits={edits}
          onDetail={false}
        />
      )}
    </fieldset>
  );
};

/** Putting the open layout back as shipped, or saying it already is. */
const Shipped = ({ stored, edits }: { stored: boolean; edits: LayoutEdits }) => {
  const { t } = useTranslation("projects");
  return stored ? (
    <Button type="button" variant="outline" size="sm" onClick={edits.resetLayout}>
      {t("layoutEditor.useShipped")}
    </Button>
  ) : (
    <p className="text-muted-foreground text-xs">{t("layoutEditor.shipped")}</p>
  );
};

/** The project whose layouts are open: whose statuses its preview draws. */
export type LayoutProject = { id: number; initiativeId: number; statuses: TaskStatusRead[] };

/** The settings of what is selected on a task's detail: the layout's own, or
 *  a part's. */
export const DetailLayoutSettings = ({
  detail,
  stored,
  fields,
  selection,
  edits,
  locked,
}: {
  /** The detail as one tree: the layout, holding its header, main and side. */
  detail: LayoutNode;
  /** Whether the project lays out its own detail, as against the shipped one. */
  stored: boolean;
  fields: ReadonlyMap<string, FieldDef>;
  selection: Selection;
  edits: LayoutEdits;
  locked: boolean;
}) => {
  const { t } = useTranslation("projects");
  return (
    <fieldset disabled={locked} className="min-w-0">
      {selection.kind === "part" ? (
        <PartSettings tree={detail} path={selection.path} fields={fields} edits={edits} onDetail />
      ) : (
        <Panel heading={t("layoutEditor.taskLayout")}>
          <p className="text-muted-foreground text-sm">{t("layoutEditor.detailHelp")}</p>
          <Shipped stored={stored} edits={edits} />
        </Panel>
      )}
    </fieldset>
  );
};

const ColumnSettings = ({
  field,
  fields,
  edits,
}: {
  field: string;
  fields: ReadonlyMap<string, FieldDef>;
  edits: LayoutEdits;
}) => {
  const { t } = useTranslation("projects");
  const keeps = fields.get(field)?.hideable === false;
  return (
    <Panel heading={t("layoutEditor.column")}>
      <p className="text-muted-foreground text-sm">
        {t(keeps ? "layoutEditor.titleHelp" : "layoutEditor.columnHelp")}
      </p>
      {keeps ? null : (
        <Button type="button" variant="outline" size="sm" onClick={() => edits.removeColumn(field)}>
          {t("layoutEditor.remove")}
        </Button>
      )}
    </Panel>
  );
};

/** One part of a card or a page: how a group or a section is arranged, what
 *  the part does, and taking it off where it may go. */
const PartSettings = ({
  tree,
  path,
  fields,
  edits,
  onDetail,
}: {
  tree: LayoutNode;
  path: NodePath;
  fields: ReadonlyMap<string, FieldDef>;
  edits: LayoutEdits;
  /** On a detail, as against a card. */
  onDetail: boolean;
}) => {
  const { t } = useTranslation(LAYOUT_NAMESPACES);
  const translate = t as TranslateFn;
  const node = nodeAt(tree, path);
  if (!node) return null;
  if (node.type === "card") {
    return (
      <Panel heading={translate("layoutEditor.card")}>
        <p className="text-muted-foreground text-sm">{translate("layoutEditor.cardHelp")}</p>
      </Panel>
    );
  }
  if ((LAYOUT_REGIONS as readonly string[]).includes(node.type)) {
    return (
      <Panel heading={translate(`layoutEditor.parts.${node.type}`)}>
        <p className="text-muted-foreground text-sm">
          {translate(`layoutEditor.regionHelp.${node.type}`)}
        </p>
      </Panel>
    );
  }
  const canRemove = removable(node, fields);
  const remove = canRemove ? (
    <Button type="button" variant="outline" size="sm" onClick={() => edits.removePart(path)}>
      {translate("layoutEditor.remove")}
    </Button>
  ) : (
    <p className="text-muted-foreground text-xs">{translate("layoutEditor.holdsTitle")}</p>
  );
  const change = (next: LayoutNode) => edits.changePart(path, next);

  if (node.type === "stack") {
    return (
      <GroupSettings node={node} onChange={change}>
        {remove}
      </GroupSettings>
    );
  }
  if (node.type === "section") {
    return (
      <SectionSettings node={node} onChange={change}>
        {remove}
      </SectionSettings>
    );
  }
  const help =
    node.type === "plugin"
      ? "layoutEditor.pluginPartHelp"
      : !canRemove
        ? onDetail
          ? "layoutEditor.detailTitleHelp"
          : "layoutEditor.titleHelp"
        : onDetail && TASK_LAYOUT.editsAField(node)
          ? "layoutEditor.toMoreFieldsHelp"
          : onDetail
            ? `layoutEditor.partHelp.${node.type}`
            : node.type === "properties"
              ? "layoutEditor.propertiesHelp"
              : "layoutEditor.fieldHelp";
  return (
    <Panel heading={translate("layoutEditor.settings")}>
      <p className="text-muted-foreground text-sm">{translate(help)}</p>
      {canRemove ? remove : null}
    </Panel>
  );
};

const Panel = ({ heading, children }: { heading: string; children: ReactNode }) => (
  <section className="space-y-4 p-4">
    <h2 className="font-medium text-sm">{heading}</h2>
    {children}
  </section>
);

/** A group's arrangement, as plain choices. Each sets one prop, and the
 *  group's default is the prop left out. */
const GroupSettings = ({
  node,
  onChange,
  children,
}: {
  node: LayoutNode;
  onChange: (next: LayoutNode) => void;
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
    <Panel heading={t("layoutEditor.group")}>
      <div className="space-y-2">
        <Label htmlFor="group-direction">{t("layoutEditor.arrange")}</Label>
        <Select
          value={props.direction === "row" ? "row" : "column"}
          onValueChange={(direction) => set("direction", direction === "row" ? "row" : undefined)}
        >
          <SelectTrigger id="group-direction">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="column">{t("layoutEditor.stacked")}</SelectItem>
            <SelectItem value="row">{t("layoutEditor.sideBySide")}</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div className="space-y-2">
        <Label htmlFor="group-gap">{t("layoutEditor.spacing")}</Label>
        <Select
          value={props.gap === "sm" ? "sm" : "xs"}
          onValueChange={(gap) => set("gap", gap === "sm" ? "sm" : undefined)}
        >
          <SelectTrigger id="group-gap">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="xs">{t("layoutEditor.tight")}</SelectItem>
            <SelectItem value="sm">{t("layoutEditor.roomy")}</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {props.direction === "row" ? flag("wrap", true, t("layoutEditor.wrap")) : null}
      {flag("align", "start", t("layoutEditor.ownWidth"))}
      {flag("tone", "muted", t("layoutEditor.muted"))}
      {children}
    </Panel>
  );
};

/** A section's title, and whether it starts folded, which only a titled
 *  section can: its title is what unfolds it. */
const SectionSettings = ({
  node,
  onChange,
  children,
}: {
  node: LayoutNode;
  onChange: (next: LayoutNode) => void;
  children: ReactNode;
}) => {
  const { t } = useTranslation("projects");
  const props = node.props ?? {};
  const title = typeof props.title === "string" ? props.title : "";
  const set = (key: string, value: unknown) => {
    const { [key]: _left, ...rest } = props;
    onChange({ ...node, props: value === undefined ? rest : { ...rest, [key]: value } });
  };
  return (
    <Panel heading={t("layoutEditor.section")}>
      <div className="space-y-2">
        <Label htmlFor="section-title">{t("layoutEditor.sectionTitle")}</Label>
        <CommittedInput
          id="section-title"
          value={title}
          optional
          onCommit={(next) => {
            const { title: _title, collapsed: _collapsed, ...rest } = props;
            onChange({
              ...node,
              props: next
                ? { ...rest, title: next, ...(props.collapsed ? { collapsed: true } : {}) }
                : rest,
            });
          }}
        />
      </div>
      <div className="flex items-center justify-between gap-2">
        <Label htmlFor="section-collapsed">{t("layoutEditor.startFolded")}</Label>
        <Switch
          id="section-collapsed"
          checked={props.collapsed === true}
          disabled={!title}
          onCheckedChange={(checked) => set("collapsed", checked ? true : undefined)}
        />
      </div>
      {children}
    </Panel>
  );
};

/** Text kept as typed and given to `onCommit` when the field is left or Enter
 *  is pressed, so one change of it is one change to undo. Left empty, it
 *  puts back what it had, unless it is `optional`. */
const CommittedInput = ({
  id,
  value,
  optional = false,
  onCommit,
}: {
  id: string;
  value: string;
  optional?: boolean;
  onCommit: (value: string) => void;
}) => {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  const commit = () => {
    const trimmed = text.trim();
    if (trimmed === value || (!trimmed && !optional)) setText(value);
    else onCommit(trimmed);
  };
  return (
    <Input
      id={id}
      value={text}
      maxLength={MAX_TITLE_LENGTH}
      onChange={(event) => setText(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Enter") commit();
      }}
    />
  );
};
