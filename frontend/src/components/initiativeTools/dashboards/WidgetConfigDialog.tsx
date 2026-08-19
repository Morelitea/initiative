/**
 * "What does this widget hook up to?" — with the answer visible while you decide.
 *
 * Setting up a binding is *authoring*: it writes the dashboard's own row and
 * takes DAC write, as distinct from a widget interacting with the data it shows,
 * which nothing here can do. Every control below chooses a source, an id, or a
 * comparison; none of them can name an endpoint, and the source list comes from
 * the served catalog, so this dialog can only ever offer what the backend
 * validator would accept.
 *
 * Two changes from the version that shipped first:
 *
 * **It previews.** The right pane runs the real widget over the real data, in
 * the same sandbox and renderer a placed tile uses. A binding that returns
 * nothing now shows that here, while it can still be fixed, rather than after
 * it lands on the canvas.
 *
 * **Its controls are generated from the source registry.** The per-source `if`
 * ladder this file used to be was a second copy of knowledge `sources.ts` now
 * holds, and it was why `conditions` — accepted and stored since dashboards
 * shipped — had no control at all.
 */

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { WidgetCatalog } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useCalendarsList } from "@/hooks/useCalendars";
import { useCounterGroup, useCounterGroupsList } from "@/hooks/useCounters";
import { useDocumentsList } from "@/hooks/useDocuments";
import { useProjects } from "@/hooks/useProjects";
import { useWidgetData, type WidgetBinding } from "@/hooks/useWidgetData";
import { useWidgetMeta } from "@/hooks/useWidgetMeta";
import { readConditions } from "@/lib/widgets/conditions";
import { catalogEntry, type DefinitionWidget } from "@/lib/widgets/definition";
import {
  type EntityKind,
  type EntityParam,
  type SourceParam,
  sourceDescriptor,
} from "@/lib/widgets/sources";
import { localized } from "@/lib/widgets/widgetMeta";

import { FilterBuilder } from "./FilterBuilder";
import { WidgetTile } from "./WidgetTile";

export interface WidgetConfigDialogProps {
  widget: DefinitionWidget | null;
  catalog: WidgetCatalog | undefined;
  /** The dashboard's initiative. Every picker below offers this initiative's
   *  content and nothing else — a dashboard is an initiative's tool, and its
   *  bindings cannot reach outside it. */
  initiativeId: number;
  /** The dashboard row, so the preview resolves exactly as the placed tile
   *  will. Absent for a widget that is not on a dashboard yet. */
  dashboardId?: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (patch: Partial<DefinitionWidget>) => void;
}

export function WidgetConfigDialog({
  widget,
  catalog,
  initiativeId,
  dashboardId,
  open,
  onOpenChange,
  onSave,
}: WidgetConfigDialogProps) {
  const { t, i18n } = useTranslation(["dashboards", "common"]);
  const { meta } = useWidgetMeta(widget?.type ?? "");

  const [title, setTitle] = useState("");
  const [binding, setBinding] = useState<WidgetBinding>({ source: "tasks" });
  const [options, setOptions] = useState<Record<string, string>>({});

  // Reset from the widget each time the dialog opens, so a cancelled edit
  // leaves nothing behind.
  useEffect(() => {
    if (!widget || !open) return;
    setTitle(widget.title ?? "");
    setBinding(widget.binding);
    setOptions(widget.options ?? {});
  }, [widget, open]);

  const entry = catalogEntry(catalog, widget?.type ?? "");
  const sources = entry?.sources ?? [];
  const source = binding.source;
  const descriptor = sourceDescriptor(source);

  // Which lists this source's controls need. Each is enabled only while its own
  // control is on screen, so opening the dialog for a counter widget does not
  // fetch this initiative's documents.
  const needs = (kind: EntityKind) =>
    open && (descriptor?.params ?? []).some((p) => p.kind === "entity" && p.entity === kind);

  const counterGroups = useCounterGroupsList(
    { initiative_id: initiativeId },
    { enabled: needs("counter_group") }
  );
  const documents = useDocumentsList(
    { document_type: "spreadsheet", initiative_id: initiativeId },
    { enabled: needs("document") }
  );
  const projects = useProjects(undefined, { enabled: needs("project") });
  const calendars = useCalendarsList(
    { initiative_id: initiativeId },
    { enabled: needs("calendar") }
  );
  // The list endpoint returns group summaries; the counters themselves come
  // from the group's own read, which is also the query the widget will use.
  const selectedGroup = useCounterGroup(binding.counter_group_id ?? null, {
    enabled: open && needs("counter") && Boolean(binding.counter_group_id),
  });

  const entityOptions = useMemo(
    (): Record<EntityKind, { value: string; label: string }[]> => ({
      project: (projects.data?.items ?? [])
        .filter((project) => project.initiative_id === initiativeId)
        .map((project) => ({ value: String(project.id), label: project.name })),
      calendar: (calendars.data?.items ?? []).map((calendar) => ({
        value: String(calendar.id),
        label: calendar.name,
      })),
      counter_group: (counterGroups.data?.items ?? []).map((group) => ({
        value: String(group.id),
        label: group.name,
      })),
      counter: (selectedGroup.data?.counters ?? []).map((counter) => ({
        value: String(counter.id),
        label: counter.name,
      })),
      document: (documents.data?.items ?? []).map((document) => ({
        value: String(document.id),
        label: document.title,
      })),
    }),
    [
      projects.data,
      calendars.data,
      counterGroups.data,
      selectedGroup.data,
      documents.data,
      initiativeId,
    ]
  );

  const setBindingValue = (patch: Partial<WidgetBinding>) =>
    setBinding((current) => ({ ...current, ...patch }));

  const save = () => {
    onSave({
      title: title.trim() || undefined,
      binding,
      options: Object.keys(options).length ? options : undefined,
    });
    onOpenChange(false);
  };

  if (!widget) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-hidden sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{t("dashboards:config.title")}</DialogTitle>
          <DialogDescription>
            {localized(meta?.description, i18n.language) ?? t("dashboards:config.description")}
          </DialogDescription>
        </DialogHeader>

        <div className="grid max-h-[60vh] gap-6 overflow-y-auto md:grid-cols-[1fr_18rem]">
          <div className="space-y-5">
            <section className="space-y-2">
              <Label htmlFor="widget-title">{t("dashboards:config.widgetTitle")}</Label>
              <Input
                id="widget-title"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder={t("dashboards:config.widgetTitlePlaceholder")}
              />
            </section>

            <section className="space-y-2">
              <h3 className="font-medium text-sm">{t("dashboards:config.sectionBinding")}</h3>
              <Label>{t("dashboards:config.source")}</Label>
              <Select
                value={source}
                onValueChange={(next) =>
                  // Changing the source drops the old source's ids rather than
                  // carrying a counter id onto a document binding.
                  setBinding({ source: next as WidgetBinding["source"] })
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {sources.map((option) => (
                    <SelectItem key={option} value={option}>
                      {t(`dashboards:bindingSource.${option}` as const)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {descriptor && (
                <p className="text-muted-foreground text-xs">
                  {t("dashboards:config.rowNoun", {
                    noun: t(`dashboards:provenance.rows_${descriptor.rowNoun}` as const, {
                      count: 1,
                    }).replace(/^1\s*/, ""),
                  })}
                </p>
              )}
            </section>

            {(descriptor?.params ?? []).map((param) => (
              <ParamControl
                key={param.key as string}
                param={param}
                binding={binding}
                entityOptions={entityOptions}
                initiativeId={initiativeId}
                onChange={setBindingValue}
              />
            ))}

            {(entry?.options ?? []).length > 0 && (
              <section className="space-y-3">
                <h3 className="font-medium text-sm">{t("dashboards:config.sectionDisplay")}</h3>
                {/* Labelled by the widget itself, so an installed listing names
                    its own options without a locale edit here. */}
                {(entry?.options ?? []).map((option) => (
                  <div key={option.key} className="space-y-2">
                    <Label>
                      {localized(meta?.options?.[option.key]?.label, i18n.language) ?? option.key}
                    </Label>
                    <Select
                      value={options[option.key] ?? option.default}
                      onValueChange={(next) =>
                        setOptions((current) => ({ ...current, [option.key]: next }))
                      }
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {option.values.map((value) => (
                          <SelectItem key={value} value={value}>
                            {localized(
                              meta?.options?.[option.key]?.values?.[value],
                              i18n.language
                            ) ?? value}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                ))}
              </section>
            )}
          </div>

          <BindingPreview
            widget={widget}
            binding={binding}
            options={options}
            initiativeId={initiativeId}
            dashboardId={dashboardId}
          />
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common:cancel")}
          </Button>
          <Button onClick={save}>{t("common:save")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** One binding parameter, drawn from what the registry says it is. */
function ParamControl({
  param,
  binding,
  entityOptions,
  initiativeId,
  onChange,
}: {
  param: SourceParam;
  binding: WidgetBinding;
  entityOptions: Record<EntityKind, { value: string; label: string }[]>;
  initiativeId: number;
  onChange: (patch: Partial<WidgetBinding>) => void;
}) {
  const { t } = useTranslation(["dashboards", "common"]);
  const key = param.key as string;

  switch (param.kind) {
    case "entity": {
      const entity = param as EntityParam;
      // A dependent picker waits for its parent: no group chosen, no counters
      // to choose from.
      if (entity.within && !binding[entity.within]) return null;
      const value = binding[param.key];
      return (
        <section className="space-y-2">
          <Label>{t(`dashboards:bindingParam.${entity.entity}` as const)}</Label>
          <Select
            value={typeof value === "number" ? String(value) : entity.required ? "" : "all"}
            onValueChange={(next) => {
              const id = next === "all" ? null : Number(next);
              // Repointing a parent invalidates the child that sat inside it.
              const cleared = entity.entity === "counter_group" ? { counter_id: null } : undefined;
              onChange({ [param.key]: id, ...cleared } as Partial<WidgetBinding>);
            }}
          >
            <SelectTrigger>
              <SelectValue placeholder={t("dashboards:config.choose")} />
            </SelectTrigger>
            <SelectContent>
              {!entity.required && (
                <SelectItem value="all">
                  {t(`dashboards:config.all_${entity.entity}` as const)}
                </SelectItem>
              )}
              {entityOptions[entity.entity].map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </section>
      );
    }

    case "enum":
      return (
        <section className="space-y-2">
          <Label>{t(`dashboards:bindingParam.${key}` as const, { defaultValue: key })}</Label>
          <Select
            value={(binding[param.key] as string) ?? param.fallback}
            onValueChange={(next) => onChange({ [param.key]: next } as Partial<WidgetBinding>)}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {param.values.map((value) => (
                <SelectItem key={value} value={value}>
                  {t(`dashboards:paramValue.${value}` as const, { defaultValue: value })}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </section>
      );

    case "window":
      return (
        <section className="space-y-2">
          <Label htmlFor={`param-${key}`}>
            {t(`dashboards:bindingParam.${key}` as const, { defaultValue: key })}
          </Label>
          <Input
            id={`param-${key}`}
            type="number"
            min={1}
            value={(binding[param.key] as number) ?? param.fallback}
            onChange={(event) =>
              onChange({
                [param.key]: Number(event.target.value) || param.fallback,
              } as Partial<WidgetBinding>)
            }
          />
          <p className="text-muted-foreground text-xs">
            {t("dashboards:config.windowDays", {
              count: (binding[param.key] as number) ?? param.fallback,
            })}
          </p>
        </section>
      );

    case "filters":
      return (
        <section className="space-y-2">
          <h3 className="font-medium text-sm">{t("dashboards:filterBuilder.heading")}</h3>
          <FilterBuilder
            value={readConditions(binding.conditions)}
            initiativeId={initiativeId}
            onChange={(next) => onChange({ conditions: next.length ? next : undefined })}
          />
        </section>
      );

    default:
      return (
        <section className="space-y-2">
          <Label htmlFor={`param-${key}`}>
            {t(`dashboards:bindingParam.${key}` as const, { defaultValue: key })}
          </Label>
          <Input
            id={`param-${key}`}
            value={(binding[param.key] as string) ?? ""}
            placeholder={param.placeholder}
            onChange={(event) =>
              onChange({ [param.key]: event.target.value } as Partial<WidgetBinding>)
            }
          />
        </section>
      );
  }
}

/**
 * The widget, running against what the controls currently say.
 *
 * The viewer's own data through the viewer's own session — the preview is not a
 * privileged read, and someone configuring a widget sees exactly what they
 * would see with it placed. It resolves nothing until the widget is on a
 * dashboard, because `app` bindings are decided against that row.
 */
function BindingPreview({
  widget,
  binding,
  options,
  initiativeId,
  dashboardId,
}: {
  widget: DefinitionWidget;
  binding: WidgetBinding;
  options: Record<string, string>;
  initiativeId: number;
  dashboardId?: number;
}) {
  const { t } = useTranslation("dashboards");
  const live = useWidgetData(binding, initiativeId, dashboardId);

  return (
    <aside className="space-y-2">
      <h3 className="font-medium text-sm">{t("config.preview")}</h3>
      <div className="h-56 overflow-hidden rounded-lg border bg-card p-2">
        <WidgetTile
          type={widget.type}
          data={live.data}
          config={options}
          isLoading={live.isLoading}
          errorCode={live.errorCode}
          chromeless
        />
      </div>
      <p className="text-muted-foreground text-xs">{t("config.previewHint")}</p>
    </aside>
  );
}
