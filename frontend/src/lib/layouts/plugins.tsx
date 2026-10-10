import { Check, ExternalLink, Minus } from "lucide-react";
import { Fragment, type ReactNode, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  CommunityPluginRead,
  PluginValueSummary,
} from "@/api/generated/initiativeAPI.schemas";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { DropdownMenuItem } from "@/components/ui/dropdown-menu";
import { Progress } from "@/components/ui/progress";
import { useCommunityPlugins, useRunPluginTaskAction } from "@/hooks/useCommunityPlugins";
import { formatDate, formatDateTime } from "@/lib/formatDate";
import { numberFormat } from "@/lib/intl";
import { cn } from "@/lib/utils";
import { type LocalizedText, localized } from "@/lib/widgets/widgetMeta";

import type { FieldDef, FieldRendererProps, LayoutItem } from "./fields";
import { Section } from "./section";

/** What a plug-in draws on an item from: the item, and the values it carries. */
type PluginItem = Pick<LayoutItem, "id" | "plugin_values">;

import type { LayoutNode } from "./tree";

// What an install's pinned definition declares for items, as the SDK's
// contract writes it (`fields`, `parts`, `actions`). Publishing checked it.

type Tone = "accent" | "positive" | "negative" | "warning" | "neutral" | "muted";

export type PluginFieldKind =
  | "text"
  | "number"
  | "date"
  | "datetime"
  | "link"
  | "badge"
  | "progress"
  | "checkbox";

export type PluginFieldDecl = {
  key: string;
  name: LocalizedText;
  kind: PluginFieldKind;
  on: string[];
  tone?: Tone;
};

export type PluginPartDecl = {
  id: string;
  name: LocalizedText;
  on: string[];
  tree: LayoutNode;
  description?: LocalizedText;
};

type PluginActionDecl = {
  id: string;
  name: LocalizedText;
  on: string[];
  confirm?: LocalizedText;
  menu?: boolean;
};

/** One install as a reader meets it on one kind of item: what it declares
 *  there, of what the server offers this reader. */
export type PluginOnItems = {
  id: number;
  /** What the community calls the install. */
  name: string;
  fields: ReadonlyMap<string, PluginFieldDecl>;
  parts: ReadonlyMap<string, PluginPartDecl>;
  actions: ReadonlyMap<string, PluginActionDecl>;
};

/** A task: the kind of item plug-ins are drawn on so far. */
const KIND = "task";

/** What a block declares on tasks, of what the server offers the reader. */
const declared = <T extends { on: string[] }>(
  definition: object,
  block: string,
  id: keyof T,
  offered: string[]
) => {
  const entries = (definition as Record<string, unknown>)[block];
  return new Map(
    (Array.isArray(entries) ? (entries as T[]) : [])
      .filter((entry) => Array.isArray(entry?.on) && entry.on.includes(KIND))
      .filter((entry) => offered.includes(String(entry[id])))
      .map((entry) => [String(entry[id]), entry])
  );
};

/** The installs whose values, parts and actions a reader meets on the tasks of
 *  one initiative. */
export const pluginsOnItems = (
  installs: Pick<
    CommunityPluginRead,
    | "id"
    | "name"
    | "enabled"
    | "definition"
    | "item_initiatives"
    | "item_fields"
    | "item_parts"
    | "item_actions"
  >[],
  initiativeId: number
): ReadonlyMap<number, PluginOnItems> =>
  new Map(
    installs
      .filter((install) => install.enabled && install.item_initiatives.includes(initiativeId))
      .map((install) => {
        return [
          install.id,
          {
            id: install.id,
            name: install.name,
            fields: declared<PluginFieldDecl>(
              install.definition,
              "fields",
              "key",
              install.item_fields
            ),
            parts: declared<PluginPartDecl>(install.definition, "parts", "id", install.item_parts),
            actions: declared<PluginActionDecl>(
              install.definition,
              "actions",
              "id",
              install.item_actions
            ),
          },
        ];
      })
  );

const NO_PLUGINS: ReadonlyMap<number, PluginOnItems> = new Map();

/** {@link pluginsOnItems} for the community's installs, once they load. */
export const usePluginsOnItems = (
  initiativeId: number | null | undefined,
  enabled = true
): ReadonlyMap<number, PluginOnItems> => {
  const { data } = useCommunityPlugins({ enabled: enabled && initiativeId != null });
  return useMemo(
    () => (data && initiativeId != null ? pluginsOnItems(data.items, initiativeId) : NO_PLUGINS),
    [data, initiativeId]
  );
};

/** A plug-in field's id in a view: by install and key, as the server checks it. */
export const pluginFieldId = (install: number, key: string) => `plugin:${install}:${key}`;

const pluginValue = (values: PluginValueSummary[] | undefined, install: number, key: string) =>
  values?.find((value) => value.plugin_id === install && value.key === key)?.value ?? null;

/** Every field the installs show on a task, after the built-ins and properties. */
export const pluginFields = (
  plugins: ReadonlyMap<number, PluginOnItems>,
  language: string
): FieldDef[] =>
  [...plugins.values()].flatMap(({ id, fields }) =>
    [...fields.values()].map(
      (field): FieldDef => ({
        id: pluginFieldId(id, field.key),
        kind: "plugin",
        source: "plugin",
        label: localized(field.name, language) ?? field.key,
        hideable: true,
        plugin: { install: id, field },
        value: (task) => {
          const value = pluginValue(task.plugin_values, id, field.key);
          return shows(field.kind, value) ? value : null;
        },
      })
    )
  );

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const isWebLink = (url: unknown): url is string =>
  typeof url === "string" && (url.startsWith("https://") || url.startsWith("http://"));

/** Whether a value is one its kind draws. A value of another shape draws
 *  nothing, as an empty one does. */
const shows = (kind: PluginFieldKind, value: unknown): boolean => {
  switch (kind) {
    case "text":
    case "date":
    case "datetime":
      return typeof value === "string" && value !== "";
    case "number":
      return typeof value === "number" && Number.isFinite(value);
    case "checkbox":
      return typeof value === "boolean";
    case "link":
      return isObject(value) && isWebLink(value.url);
    case "badge":
      return isObject(value) && typeof value.text === "string" && value.text !== "";
    case "progress":
      return (
        isObject(value) &&
        typeof value.value === "number" &&
        typeof value.max === "number" &&
        value.max > 0
      );
  }
};

const TEXT_TONE: Record<Tone, string> = {
  accent: "text-primary",
  positive: "text-success",
  negative: "text-destructive",
  warning: "text-warning",
  neutral: "text-foreground",
  muted: "text-muted-foreground",
};

const BADGE_TONE: Record<Tone, string> = {
  accent: "border-primary/40 text-primary",
  positive: "border-success/40 text-success",
  negative: "border-destructive/40 text-destructive",
  warning: "border-warning/40 text-warning",
  neutral: "",
  muted: "text-muted-foreground",
};

const toneOf = (tone: unknown, fallback: Tone | undefined): Tone =>
  typeof tone === "string" && Object.hasOwn(TEXT_TONE, tone)
    ? (tone as Tone)
    : (fallback ?? "neutral");

/** A plug-in value, drawn as its kind is. */
const PluginValue = ({ field, value }: { field: PluginFieldDecl; value: unknown }) => {
  const { t, i18n } = useTranslation("common");
  if (!shows(field.kind, value)) return null;
  switch (field.kind) {
    case "text":
      return <span className="wrap-break-word">{value as string}</span>;
    case "number":
      return <span>{numberFormat(i18n.language).format(value as number)}</span>;
    case "date":
      return <span>{formatDate(value)}</span>;
    case "datetime":
      return <span>{formatDateTime(value)}</span>;
    case "checkbox":
      return value ? (
        <Check className="h-4 w-4" aria-label={t("yes")} />
      ) : (
        <Minus className="h-4 w-4 text-muted-foreground" aria-label={t("no")} />
      );
    case "link": {
      const link = value as { url: string; text?: unknown };
      return (
        <a
          href={link.url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex min-w-0 items-center gap-1 text-primary underline-offset-4 hover:underline"
        >
          <span className="truncate">
            {typeof link.text === "string" && link.text ? link.text : link.url}
          </span>
          <ExternalLink className="h-3 w-3 shrink-0" aria-hidden="true" />
        </a>
      );
    }
    case "badge": {
      const badge = value as { text: string; tone?: unknown };
      return (
        <Badge variant="outline" className={BADGE_TONE[toneOf(badge.tone, field.tone)]}>
          {badge.text}
        </Badge>
      );
    }
    case "progress": {
      const progress = value as { value: number; max: number };
      const percent = Math.min(100, Math.max(0, (progress.value / progress.max) * 100));
      return (
        <Progress
          value={percent}
          aria-label={field.key}
          className="w-24"
          title={`${numberFormat(i18n.language).format(progress.value)} / ${numberFormat(i18n.language).format(progress.max)}`}
        />
      );
    }
  }
};

/** A plug-in field as a view draws it: its value in a cell, and its name
 *  beside its value on a card. */
export const PluginField = ({ value, field, variant }: FieldRendererProps) => {
  if (!field.plugin) return null;
  const drawn = <PluginValue field={field.plugin.field} value={value} />;
  if (variant === "cell") return drawn;
  return (
    <span className="inline-flex min-w-0 items-center gap-1 text-xs">
      <span className="text-muted-foreground">{field.label}</span>
      {drawn}
    </span>
  );
};

/** A plug-in field on an item's page: its name above its value, which the
 *  plug-in alone changes. */
export const PluginFieldOnDetail = ({ field, item }: { field: FieldDef; item: PluginItem }) => {
  if (!field.plugin) return null;
  const { install, field: declared } = field.plugin;
  const value = pluginValue(item.plugin_values, install, declared.key);
  if (!shows(declared.kind, value)) return null;
  return (
    <div className="space-y-1">
      <p className="text-muted-foreground text-xs">{field.label}</p>
      <div className="text-sm">
        <PluginValue field={declared} value={value} />
      </div>
    </div>
  );
};

// -- Actions --------------------------------------------------------------------

/** Runs a plug-in's actions on a task, asking first when the action says to. */
const useActionRunner = (taskId: number) => {
  const { t, i18n } = useTranslation("common");
  const run = useRunPluginTaskAction();
  const [asking, setAsking] = useState<{ plugin: number; action: PluginActionDecl } | null>(null);
  const start = (plugin: number, action: PluginActionDecl) => {
    if (action.confirm) setAsking({ plugin, action });
    else run.mutate({ pluginId: plugin, actionId: action.id, taskId });
  };
  const dialog = (
    <ConfirmDialog
      open={asking !== null}
      onOpenChange={(open) => {
        if (!open) setAsking(null);
      }}
      title={asking ? (localized(asking.action.confirm, i18n.language) ?? "") : ""}
      confirmLabel={
        asking ? (localized(asking.action.name, i18n.language) ?? asking.action.id) : ""
      }
      cancelLabel={t("cancel")}
      onConfirm={() => {
        if (asking) run.mutate({ pluginId: asking.plugin, actionId: asking.action.id, taskId });
        setAsking(null);
      }}
    />
  );
  return { start, pending: run.isPending, dialog };
};

/** The task menu's entries for the actions plug-ins offer there, and the
 *  question one asks before it runs, which stays when the menu closes. */
export const usePluginMenuActions = (taskId: number, initiativeId: number | null | undefined) => {
  const { i18n } = useTranslation();
  const plugins = usePluginsOnItems(initiativeId);
  const runner = useActionRunner(taskId);
  const items = [...plugins.values()].flatMap(({ id, actions }) =>
    [...actions.values()]
      .filter((action) => action.menu)
      .map((action) => (
        <DropdownMenuItem
          key={`${id}:${action.id}`}
          disabled={runner.pending}
          onSelect={() => runner.start(id, action)}
        >
          {localized(action.name, i18n.language) ?? action.id}
        </DropdownMenuItem>
      ))
  );
  return { items, dialog: runner.dialog };
};

// -- Parts ----------------------------------------------------------------------

const GAP = { none: "gap-0", small: "gap-1", medium: "gap-2", large: "gap-4" };
const BUTTON_VARIANT = { primary: "default", secondary: "outline", ghost: "ghost" } as const;

type Drawing = {
  plugin: PluginOnItems;
  task: PluginItem;
  language: string;
  start: (plugin: number, action: PluginActionDecl) => void;
  pending: boolean;
};

const drawChildren = (node: LayoutNode, drawing: Drawing): ReactNode =>
  node.children?.map((child, index) => (
    // biome-ignore lint/suspicious/noArrayIndexKey: a part's tree is fixed by its manifest
    <Fragment key={index}>{drawPart(child, drawing)}</Fragment>
  ));

const drawPart = (node: LayoutNode, drawing: Drawing): ReactNode => {
  const props = node.props ?? {};
  const { plugin, task, language } = drawing;
  switch (node.type) {
    case "section":
      return (
        <Section
          title={localized(props.title as LocalizedText | undefined, language)}
          collapsed={props.collapsed === true}
          spacing="space-y-2"
        >
          {drawChildren(node, drawing)}
        </Section>
      );
    case "stack":
      return (
        <div
          className={cn(
            "flex min-w-0",
            props.direction === "row" ? "flex-row items-center" : "flex-col",
            props.wrap === true && "flex-wrap",
            GAP[(props.gap as keyof typeof GAP) ?? "medium"] ?? GAP.medium
          )}
        >
          {drawChildren(node, drawing)}
        </div>
      );
    case "field":
    case "value": {
      const field = plugin.fields.get(String(props.field));
      if (!field) return null;
      const value = pluginValue(task.plugin_values, plugin.id, field.key);
      if (!shows(field.kind, value)) return null;
      const drawn = <PluginValue field={field} value={value} />;
      if (node.type === "value") return drawn;
      return (
        <div className="space-y-1">
          <p className="text-muted-foreground text-xs">
            {localized(field.name, language) ?? field.key}
          </p>
          <div className="text-sm">{drawn}</div>
        </div>
      );
    }
    case "text": {
      const text = localized(props.text as LocalizedText | undefined, language);
      return text ? (
        <p className={cn("wrap-break-word text-sm", TEXT_TONE[toneOf(props.tone, "neutral")])}>
          {text}
        </p>
      ) : null;
    }
    case "button": {
      const action = plugin.actions.get(String(props.action));
      if (!action) return null;
      return (
        <Button
          type="button"
          size="sm"
          variant={
            BUTTON_VARIANT[(props.variant as keyof typeof BUTTON_VARIANT) ?? "secondary"] ??
            "outline"
          }
          disabled={drawing.pending}
          onClick={() => drawing.start(plugin.id, action)}
        >
          {localized(action.name, language) ?? action.id}
        </Button>
      );
    }
    default:
      return null;
  }
};

/** One of a plug-in's parts on a task, drawn from its manifest's tree. A part
 *  the install no longer declares, or one placed where its plug-in does not
 *  reach the reader, draws nothing. */
export const PluginPartView = ({
  plugins,
  pluginId,
  partId,
  task,
}: {
  plugins: ReadonlyMap<number, PluginOnItems> | undefined;
  pluginId: number;
  partId: string;
  task: PluginItem;
}) => {
  const { i18n } = useTranslation();
  const runner = useActionRunner(task.id);
  const plugin = plugins?.get(pluginId);
  const part = plugin?.parts.get(partId);
  if (!plugin || !part) return null;
  return (
    <>
      {drawPart(part.tree, {
        plugin,
        task,
        language: i18n.language,
        start: runner.start,
        pending: runner.pending,
      })}
      {runner.dialog}
    </>
  );
};
