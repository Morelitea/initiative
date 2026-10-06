/**
 * A project listing, drawn from the listing alone.
 *
 * The status columns in order, each holding its tasks as cards, and the
 * properties the project brings. Nothing here reads the viewer's community:
 * the real board fetches its tasks, and a listing that is not installed has
 * none to fetch, so this draws the envelope with the board's own small pieces
 * (status, priority, checklist progress, property chips) instead.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { type PropertySummary, PropertyType } from "@/api/generated/initiativeAPI.schemas";
import { priorityVariant } from "@/components/projects/projectTasksConfig";
import { PropertyValueCell } from "@/components/properties/PropertyValueCell";
import { iconForPropertyType } from "@/components/properties/propertyTypeIcons";
import { TaskChecklistProgress } from "@/components/tasks/TaskChecklistProgress";
import { TaskStatusOption } from "@/components/tasks/TaskStatusOption";
import { Badge } from "@/components/ui/badge";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  dayOffsetsFrom,
  type ProjectListingEnvelope,
  type ProjectListingPropertyDefinition,
  type ProjectListingPropertyValue,
  readProjectEnvelope,
} from "@/lib/projectListing";
import { defaultsForCategory } from "@/lib/taskStatusDefaults";

/** The property types a card shows. Dates and people are left off: a listing
 *  carries no people, and its dates only mean something once installed. */
const CARD_PROPERTY_TYPES: ReadonlySet<PropertyType> = new Set([
  PropertyType.text,
  PropertyType.number,
  PropertyType.select,
  PropertyType.multi_select,
]);

/** A task's value in the shape the property chip draws. */
const toSummary = (
  value: ProjectListingPropertyValue,
  definitions: ProjectListingPropertyDefinition[],
  index: number
): PropertySummary => ({
  property_id: index,
  name: value.property_name,
  type: value.property_type,
  options: definitions.find((d) => d.name === value.property_name)?.options ?? null,
  value: value.value_text ?? value.value_number ?? value.value_boolean ?? value.value_json,
});

type Showing = "blank" | "example";

export interface ProjectListingPreviewProps {
  definition: unknown;
  example: unknown;
}

export function ProjectListingPreview({ definition, example }: ProjectListingPreviewProps) {
  const { t } = useTranslation(["marketplace", "projects", "tasks"]);
  const blank = readProjectEnvelope(definition);
  const filled = readProjectEnvelope(example);
  const [showing, setShowing] = useState<Showing>("blank");
  const envelope = showing === "example" && filled ? filled : blank;

  if (!envelope) return null;

  return (
    <div className="space-y-4">
      {filled ? (
        <ToggleGroup
          type="single"
          variant="outline"
          className="justify-start"
          aria-label={t("marketplace:projectPreview.showing")}
          value={showing}
          onValueChange={(next) => next && setShowing(next as Showing)}
        >
          <ToggleGroupItem value="blank" className="h-8 px-3">
            {t("marketplace:projectPreview.blank")}
          </ToggleGroupItem>
          <ToggleGroupItem value="example" className="h-8 px-3">
            {t("marketplace:projectPreview.example")}
          </ToggleGroupItem>
        </ToggleGroup>
      ) : null}
      <ProjectBoard envelope={envelope} />
    </div>
  );
}

function ProjectBoard({ envelope }: { envelope: ProjectListingEnvelope }) {
  const { t } = useTranslation(["marketplace", "projects", "tasks"]);
  const statuses = [...envelope.task_statuses].sort((a, b) => a.position - b.position);
  const definitions = [...envelope.property_definitions].sort((a, b) => a.position - b.position);
  const offsetOf = dayOffsetsFrom(envelope);

  /** "Day 3" for the first fortnight, "Week 4" after it. */
  const readable = (date: string | null | undefined): string | null => {
    const offset = offsetOf(date);
    if (offset === null) return null;
    return offset < 14
      ? t("marketplace:projectPreview.day", { day: offset + 1 })
      : t("marketplace:projectPreview.week", { week: Math.floor(offset / 7) + 1 });
  };

  return (
    <div className="space-y-4">
      <div className="flex gap-3 overflow-x-auto pb-2">
        {statuses.map((status) => {
          // Keyed by place in the envelope: titles need not be unique.
          const tasks = envelope.tasks.flatMap((task, key) =>
            task.status_name === status.name ? [{ task, key }] : []
          );
          const look = defaultsForCategory(status.category);
          return (
            <section
              key={status.name}
              aria-label={status.name}
              className="w-64 shrink-0 space-y-2 rounded-lg border bg-muted/40 p-2"
              style={{ borderTopColor: status.color ?? look.color, borderTopWidth: 3 }}
            >
              <h3 className="flex items-center justify-between gap-2 px-1 font-medium text-sm">
                <TaskStatusOption
                  status={{
                    name: status.name,
                    // A status without its own look takes its category's, as
                    // installing it does.
                    icon: status.icon ?? look.icon,
                    color: status.color ?? look.color,
                  }}
                />
                <span className="text-muted-foreground text-xs tabular-nums">{tasks.length}</span>
              </h3>
              {tasks.length === 0 ? (
                <p className="px-1 py-2 text-muted-foreground text-xs">
                  {t("marketplace:projectPreview.noTasks")}
                </p>
              ) : (
                tasks.map(({ task, key }) => {
                  const due = readable(task.due_date);
                  const done = task.checklist.filter((item) => item.done).length;
                  return (
                    <article
                      key={key}
                      className="space-y-2 rounded-md border bg-card p-2.5 text-sm shadow-xs"
                    >
                      <p className="wrap-break-word font-medium">{task.title}</p>
                      {due ? (
                        <p className="text-muted-foreground text-xs">
                          {t("projects:kanban.due", { date: due })}
                        </p>
                      ) : null}
                      <TaskChecklistProgress
                        progress={{ completed: done, total: task.checklist.length }}
                      />
                      <div className="flex flex-wrap gap-1.5">
                        <Badge variant={priorityVariant[task.priority]}>
                          {t(`tasks:priority.${task.priority}`)}
                        </Badge>
                        {task.properties
                          .filter((value) => CARD_PROPERTY_TYPES.has(value.property_type))
                          .map((value, i) => (
                            <PropertyValueCell
                              key={value.property_name}
                              summary={toSummary(value, definitions, i)}
                              variant="chip"
                            />
                          ))}
                      </div>
                    </article>
                  );
                })
              )}
            </section>
          );
        })}
      </div>

      {definitions.length ? (
        <div className="space-y-2">
          <h3 className="font-medium text-sm">{t("marketplace:projectPreview.properties")}</h3>
          <ul className="flex flex-wrap gap-2">
            {definitions.map((definition) => {
              const Icon = iconForPropertyType(definition.type);
              return (
                <li
                  key={definition.name}
                  className="inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs"
                >
                  <Icon className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
                  <span className="font-medium">{definition.name}</span>
                  {definition.options?.length ? (
                    <span className="text-muted-foreground">
                      {definition.options.map((option) => option.label).join(", ")}
                    </span>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
