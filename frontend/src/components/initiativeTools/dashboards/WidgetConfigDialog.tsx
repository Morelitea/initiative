/**
 * "What does this widget hook up to?"
 *
 * Setting up a widget's binding is *authoring* — it writes the dashboard's own
 * row and takes DAC write — as distinct from a widget interacting with the data
 * it shows, which nothing here can do. Every control below chooses a source or
 * an id; none of them can name an endpoint, and the source list comes from the
 * served catalog, so this dialog can only ever offer what the backend validator
 * would accept.
 */

import { useEffect, useState } from "react";
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
import type { WidgetBinding } from "@/hooks/useWidgetData";
import { useWidgetMeta } from "@/hooks/useWidgetMeta";
import { catalogEntry, type DefinitionWidget } from "@/lib/widgets/definition";
import { localized } from "@/lib/widgets/widgetMeta";

export interface WidgetConfigDialogProps {
  widget: DefinitionWidget | null;
  catalog: WidgetCatalog | undefined;
  /** The dashboard's initiative. Every picker below offers this initiative's
   *  content and nothing else — a dashboard is an initiative's tool, and its
   *  bindings cannot reach outside it. */
  initiativeId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (patch: Partial<DefinitionWidget>) => void;
}

/** Count buckets the `task_counts` source understands. Only `day` has a
 *  calendar shape, which is what a heatmap needs. */
const BUCKETS = ["status_category", "status", "priority", "project", "assignee", "day"] as const;

export function WidgetConfigDialog({
  widget,
  catalog,
  initiativeId,
  open,
  onOpenChange,
  onSave,
}: WidgetConfigDialogProps) {
  const { t } = useTranslation(["dashboards", "common"]);
  const { meta } = useWidgetMeta(widget?.type ?? "");
  const { i18n } = useTranslation();

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

  const needsCounterGroup = source === "counter" || source === "counter_group";
  const needsDocument = source === "sheet_range";

  // All four pickers ask the server for this initiative's content only; the
  // projects list has no initiative filter of its own, so it narrows below.
  const counterGroups = useCounterGroupsList(
    { initiative_id: initiativeId },
    { enabled: open && needsCounterGroup }
  );
  const documents = useDocumentsList(
    { document_type: "spreadsheet", initiative_id: initiativeId },
    { enabled: open && needsDocument }
  );
  const projects = useProjects(undefined, { enabled: open && source === "tasks" });
  const calendars = useCalendarsList(
    { initiative_id: initiativeId },
    { enabled: open && source === "calendar_entries" }
  );

  // The list endpoint returns group summaries; the counters themselves come
  // from the group's own read, which is also the query the widget will use.
  const selectedGroup = useCounterGroup(binding.counter_group_id ?? null, {
    enabled: open && source === "counter" && Boolean(binding.counter_group_id),
  });

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
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("dashboards:config.title")}</DialogTitle>
          <DialogDescription>
            {localized(meta?.description, i18n.language) ?? t("dashboards:config.description")}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="widget-title">{t("dashboards:config.widgetTitle")}</Label>
            <Input
              id="widget-title"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder={t("dashboards:config.widgetTitlePlaceholder")}
            />
          </div>

          <div className="space-y-2">
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
          </div>

          {needsCounterGroup && (
            <div className="space-y-2">
              <Label>{t("dashboards:bindingSource.counter_group")}</Label>
              <Select
                value={binding.counter_group_id ? String(binding.counter_group_id) : ""}
                onValueChange={(next) =>
                  setBindingValue({ counter_group_id: Number(next), counter_id: null })
                }
              >
                <SelectTrigger>
                  <SelectValue placeholder={t("dashboards:config.choose")} />
                </SelectTrigger>
                <SelectContent>
                  {(counterGroups.data?.items ?? []).map((group) => (
                    <SelectItem key={group.id} value={String(group.id)}>
                      {group.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {source === "counter" && selectedGroup.data && (
            <div className="space-y-2">
              <Label>{t("dashboards:bindingSource.counter")}</Label>
              <Select
                value={binding.counter_id ? String(binding.counter_id) : ""}
                onValueChange={(next) => setBindingValue({ counter_id: Number(next) })}
              >
                <SelectTrigger>
                  <SelectValue placeholder={t("dashboards:config.choose")} />
                </SelectTrigger>
                <SelectContent>
                  {(selectedGroup.data.counters ?? []).map((counter) => (
                    <SelectItem key={counter.id} value={String(counter.id)}>
                      {counter.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {needsDocument && (
            <>
              <div className="space-y-2">
                <Label>{t("dashboards:config.spreadsheet")}</Label>
                <Select
                  value={binding.document_id ? String(binding.document_id) : ""}
                  onValueChange={(next) => setBindingValue({ document_id: Number(next) })}
                >
                  <SelectTrigger>
                    <SelectValue placeholder={t("dashboards:config.choose")} />
                  </SelectTrigger>
                  <SelectContent>
                    {(documents.data?.items ?? []).map((document) => (
                      <SelectItem key={document.id} value={String(document.id)}>
                        {document.title}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-2">
                  <Label htmlFor="sheet-name">{t("dashboards:config.sheet")}</Label>
                  <Input
                    id="sheet-name"
                    value={binding.sheet ?? ""}
                    onChange={(event) => setBindingValue({ sheet: event.target.value })}
                    placeholder={t("dashboards:config.sheetPlaceholder")}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="sheet-range">{t("dashboards:config.range")}</Label>
                  <Input
                    id="sheet-range"
                    value={binding.range ?? ""}
                    onChange={(event) => setBindingValue({ range: event.target.value })}
                    placeholder="A1:B10"
                  />
                </div>
              </div>
            </>
          )}

          {source === "tasks" && (
            <div className="space-y-2">
              <Label>{t("dashboards:config.project")}</Label>
              <Select
                value={binding.project_id ? String(binding.project_id) : "all"}
                onValueChange={(next) =>
                  setBindingValue({ project_id: next === "all" ? null : Number(next) })
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">{t("dashboards:config.allProjects")}</SelectItem>
                  {(projects.data?.items ?? [])
                    .filter((project) => project.initiative_id === initiativeId)
                    .map((project) => (
                      <SelectItem key={project.id} value={String(project.id)}>
                        {project.name}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {source === "calendar_entries" && (
            <div className="space-y-2">
              <Label>{t("dashboards:bindingSource.calendar_entries")}</Label>
              <Select
                value={binding.calendar_id ? String(binding.calendar_id) : "all"}
                onValueChange={(next) =>
                  setBindingValue({ calendar_id: next === "all" ? null : Number(next) })
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">{t("dashboards:config.allCalendars")}</SelectItem>
                  {(calendars.data?.items ?? []).map((calendar) => (
                    <SelectItem key={calendar.id} value={String(calendar.id)}>
                      {calendar.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {source === "task_counts" && (
            <div className="space-y-2">
              <Label>{t("dashboards:config.groupBy")}</Label>
              <Select
                value={binding.bucket ?? "status_category"}
                onValueChange={(next) =>
                  setBindingValue({ bucket: next as WidgetBinding["bucket"] })
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {BUCKETS.map((bucket) => (
                    <SelectItem key={bucket} value={bucket}>
                      {t(`dashboards:config.bucket.${bucket}` as const)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {/* Display options, labelled by the widget itself. */}
          {(entry?.options ?? []).map((option) => (
            <div key={option.key} className="space-y-2">
              <Label>
                {localized(meta?.options?.[option.key]?.label, i18n.language) ?? option.key}
              </Label>
              <Select
                value={options[option.key] ?? option.values[0]}
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
                      {localized(meta?.options?.[option.key]?.values?.[value], i18n.language) ??
                        value}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ))}
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
