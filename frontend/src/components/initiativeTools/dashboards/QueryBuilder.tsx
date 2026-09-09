/**
 * Building a query by clicking.
 *
 * A dashboard has to be buildable by somebody who does not write SQL, so this
 * is the primary way a widget is bound and the statement is what it produces —
 * not the other way round. What is chosen here is a *description*: which
 * dataset, which columns, what narrows it, what it is grouped by. The server
 * writes the SQL from that description and hands back both the statement to
 * store and the columns the widget's slots can be filled from.
 *
 * The SQL is shown, read-only, because somebody should be able to see what
 * their clicking produced — and because it is the thing that gets stored.
 */

import { Plus, X } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import {
  DatasetName,
  type QueryBuildRequest,
  type QueryColumnSpec,
} from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useFieldCatalog } from "@/hooks/useFieldCatalog";
import { useFieldCatalogs } from "@/hooks/useQueryVocabulary";

/** The datasets a query may name. Read from the generated enum, which is the
 *  backend's own registry — so a dataset declared there is offered here on the
 *  next generation rather than after an edit to a second list. */
const DATASETS = Object.values(DatasetName) as DatasetName[];

/** What a column may be reduced to, mirroring the builder's own set. */
const AGGREGATES = ["count", "sum", "avg", "min", "max"] as const;
const BUCKETS = ["day", "week", "month", "quarter", "year"] as const;

/** The one column that is not a field: how many rows there are. */
const COUNT_ALL: QueryColumnSpec = { field: "*", aggregate: "count", alias: "count" };

export interface QueryBuilderProps {
  spec: QueryBuildRequest;
  onChange: (spec: QueryBuildRequest) => void;
}

export function QueryBuilder({ spec, onChange }: QueryBuilderProps) {
  const { t } = useTranslation(["dashboards", "common"]);
  const { fields, relations } = useFieldCatalog(spec.dataset as DatasetName);
  // What each related dataset holds. A relation says only its name and where
  // it arrives; what may be named there is that dataset's own description, so
  // it is read the same way this one is.
  const related = useFieldCatalogs(relations.map((relation) => relation.dataset));

  // Only what a statement can actually select: a computed field has no column
  // for a SELECT to read, and offering one would produce a query the server
  // then refuses.
  const selectable = useMemo(
    () => fields.filter((field) => !field.field.endsWith("_ids")),
    [fields]
  );

  /** What a related dataset offers, prefixed with the relation that reaches
   *  it — which is exactly how a statement names one. */
  const reachable = useMemo(
    () =>
      relations.flatMap((relation) => {
        const holder = related.find((entry) => entry.dataset === relation.dataset);
        return (holder?.fields ?? [])
          .filter((field) => !field.name.endsWith("_ids"))
          .map((field) => ({
            name: `${relation.name}.${field.name}`,
            type: field.type,
            relation: relation.name,
          }));
      }),
    [relations, related]
  );

  const byName = useMemo(
    () =>
      new Map<string, { kind?: string }>([
        ...selectable.map((field) => [field.field, field] as const),
        ...reachable.map((field) => [field.name, { kind: field.type }] as const),
      ]),
    [selectable, reachable]
  );

  const patch = (next: Partial<QueryBuildRequest>) => onChange({ ...spec, ...next });

  const setColumn = (index: number, column: QueryColumnSpec) =>
    patch({ columns: spec.columns.map((held, at) => (at === index ? column : held)) });

  const isDate = (field?: { kind?: string }) => field?.kind === "date";

  return (
    <div className="space-y-4">
      <section className="space-y-2">
        <Label>{t("dashboards:builder.dataset")}</Label>
        <Select
          value={spec.dataset}
          onValueChange={(dataset) =>
            // A different dataset has different fields, so nothing chosen
            // against the old one survives.
            onChange({ dataset, columns: [COUNT_ALL], where: [], group_by: [] })
          }
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {DATASETS.map((name) => (
              <SelectItem key={name} value={name}>
                {t(`dashboards:dataset.${name}` as const, { defaultValue: name })}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </section>

      <section className="space-y-2">
        <Label>{t("dashboards:builder.columns")}</Label>
        {spec.columns.map((column, index) => (
          // Two columns may read the same field (a count of it and the field
          // itself), so the position is what tells the rows apart.
          // biome-ignore lint/suspicious/noArrayIndexKey: position is the identity here
          <div key={index} className="flex items-center gap-2">
            <Select
              value={column.field}
              onValueChange={(fieldName) =>
                setColumn(index, {
                  ...column,
                  field: fieldName,
                  // A rounding that meant something for a date means nothing
                  // for the column that replaced it.
                  bucket: isDate(byName.get(fieldName)) ? column.bucket : null,
                  alias: null,
                })
              }
            >
              <SelectTrigger className="flex-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="*">{t("dashboards:builder.everyRow")}</SelectItem>
                {selectable.map((field) => (
                  <SelectItem key={field.field} value={field.field}>
                    {field.field}
                  </SelectItem>
                ))}
                {reachable.map((field) => (
                  <SelectItem key={field.name} value={field.name}>
                    {field.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select
              value={column.aggregate ?? "none"}
              onValueChange={(aggregate) =>
                setColumn(index, {
                  ...column,
                  aggregate: aggregate === "none" ? null : aggregate,
                })
              }
            >
              <SelectTrigger className="w-32">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">{t("dashboards:builder.asItIs")}</SelectItem>
                {AGGREGATES.map((aggregate) => (
                  <SelectItem key={aggregate} value={aggregate}>
                    {t(`dashboards:aggregate.${aggregate}` as const, {
                      defaultValue: aggregate,
                    })}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            {isDate(byName.get(column.field)) && (
              <Select
                value={column.bucket ?? "none"}
                onValueChange={(bucket) =>
                  setColumn(index, { ...column, bucket: bucket === "none" ? null : bucket })
                }
              >
                <SelectTrigger className="w-32">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">{t("dashboards:builder.exactTime")}</SelectItem>
                  {BUCKETS.map((bucket) => (
                    <SelectItem key={bucket} value={bucket}>
                      {t(`dashboards:bucket.${bucket}` as const, { defaultValue: bucket })}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}

            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-8 w-8 shrink-0"
              aria-label={t("dashboards:builder.removeColumn")}
              disabled={spec.columns.length <= 1}
              onClick={() => patch({ columns: spec.columns.filter((_held, at) => at !== index) })}
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
        ))}
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() =>
            patch({
              columns: [
                ...spec.columns,
                selectable[0] ? { field: selectable[0].field } : COUNT_ALL,
              ],
            })
          }
        >
          <Plus className="mr-1 h-4 w-4" />
          {t("dashboards:builder.addColumn")}
        </Button>
      </section>

      <section className="space-y-2">
        <Label>{t("dashboards:builder.groupBy")}</Label>
        <Select
          value={spec.group_by?.[0] ?? "none"}
          onValueChange={(name) => patch({ group_by: name === "none" ? [] : [name] })}
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="none">{t("dashboards:builder.everythingTogether")}</SelectItem>
            {spec.columns
              .filter((column) => !column.aggregate)
              .map((column) => column.alias || column.field)
              .filter((name) => name !== "*")
              .map((name) => (
                <SelectItem key={name} value={name}>
                  {name}
                </SelectItem>
              ))}
          </SelectContent>
        </Select>
        <p className="text-muted-foreground text-xs">{t("dashboards:builder.groupByHelp")}</p>
      </section>
    </div>
  );
}
