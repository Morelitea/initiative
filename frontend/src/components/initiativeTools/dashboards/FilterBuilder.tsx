/**
 * Authoring the filter half of a data view.
 *
 * The binding has accepted `conditions` since dashboards shipped and nothing
 * could write one, so every task-backed widget has been showing every task in
 * its initiative. This is the control that was missing.
 *
 * Two decisions worth stating:
 *
 * **Flat by default, one group deep at most.** The endpoint's parser caps group
 * nesting, and the host already spends a level wrapping the dashboard's own
 * initiative — so a second level of grouping here is the last one that can
 * survive the round trip. The builder offers exactly that and says so, rather
 * than letting someone compose a filter that 400s the whole query on save.
 *
 * **Dates are relative unless you ask otherwise.** A dashboard is a standing
 * question, not a snapshot; "due in the next 30 days" stays true and
 * "due before 30 September" is wrong by October. Absolute is still there for
 * the cases that mean a real date — a launch, a quarter end.
 *
 * Every value control is the app's own: the same status, priority, member and
 * tag primitives the task filters use, over lists the viewer can already see.
 */

import type { TFunction } from "i18next";
import { Plus, X } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { MultiSelect } from "@/components/ui/multi-select";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useFieldCatalog } from "@/hooks/useFieldCatalog";
import { useInitiative } from "@/hooks/useInitiatives";
import { useProjects } from "@/hooks/useProjects";
import { useTags } from "@/hooks/useTags";
import { getUserDisplayName } from "@/lib/userDisplay";
import {
  type ConditionValue,
  type FilterFieldSpec,
  type FilterLeaf,
  type FilterNode,
  type FilterOp,
  fieldSpec,
  isGroup,
  isRelativeDate,
  optionLabelKey,
} from "@/lib/widgets/conditions";

export interface FilterBuilderProps {
  value: FilterNode[];
  onChange: (next: FilterNode[]) => void;
  /** The dashboard's initiative — every option list below is its own. */
  initiativeId: number;
}

const emptyLeaf = (): FilterLeaf => ({ field: "status_category", op: "in_", value: [] });

/** A field's label, falling back to its name.
 *
 *  The names come from the server now, so they cannot be checked against the
 *  locale file at compile time the way a literal union was. A missing label
 *  therefore degrades to the field's own name — readable, and visible enough in
 *  review to be fixed — rather than rendering a raw i18n key. */
const fieldLabel = (name: string, t: TFunction<readonly ["dashboards", "common"]>): string =>
  t(`dashboards:filterField.${name}` as never, { defaultValue: name });

export function FilterBuilder({ value, onChange, initiativeId }: FilterBuilderProps) {
  const { t } = useTranslation(["dashboards", "tasks", "common"]);

  // The option lists. Each is a query the canvas or dialog already makes, and
  // each returns only what this viewer can see — so an author cannot filter by
  // something they could not have found in the app anyway.
  const projects = useProjects();
  const tags = useTags();
  const initiative = useInitiative(initiativeId);

  // What may be filtered on, from the server's field registry — one
  // declaration, so a control cannot offer an operator the engine refuses.
  const { fields, isLoading: fieldsLoading } = useFieldCatalog("tasks");

  const options = useMemo(
    () => ({
      project: (projects.data?.items ?? [])
        .filter((project) => project.initiative_id === initiativeId)
        .map((project) => ({ value: String(project.id), label: project.name })),
      tag: (tags.data ?? []).map((tag) => ({ value: String(tag.id), label: tag.name })),
      member: [
        { value: "me", label: t("dashboards:provenance.me") },
        ...(initiative.data?.members ?? []).map((member) => ({
          value: String(member.user.id),
          label: getUserDisplayName(member.user, String(member.user.id)),
        })),
      ],
    }),
    [projects.data, tags.data, initiative.data, initiativeId, t]
  );

  const replaceAt = (index: number, node: FilterNode | null) => {
    const next = value.slice();
    if (node === null) next.splice(index, 1);
    else next[index] = node;
    onChange(next);
  };

  // One group level is all that survives the round trip, so the affordance is
  // offered only while none exists.
  const hasGroup = value.some(isGroup);

  // Until the declarations arrive, a condition has no field to be read
  // against: its operator list and its value control would both fall back to
  // the plainest thing they can draw, and editing one then rewrites a saved
  // filter into whatever that plain control emitted. So the rows wait.
  if (fieldsLoading) {
    return <p className="text-muted-foreground text-xs">{t("dashboards:filterBuilder.loading")}</p>;
  }

  return (
    <div className="space-y-2">
      {value.length === 0 && (
        <p className="text-muted-foreground text-xs">{t("dashboards:filterBuilder.empty")}</p>
      )}

      {value.map((node, index) => (
        <div
          // Conditions have no id; position is the identity the author sees and
          // edits, and reordering is not offered.
          // biome-ignore lint/suspicious/noArrayIndexKey: positional by design
          key={index}
          className="rounded-md border bg-muted/30 p-2"
        >
          {isGroup(node) ? (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label className="text-xs">{t("dashboards:filterBuilder.group")}</Label>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-6 w-6"
                  aria-label={t("dashboards:filterBuilder.remove")}
                  onClick={() => replaceAt(index, null)}
                >
                  <X className="h-3.5 w-3.5" />
                </Button>
              </div>
              <p className="text-muted-foreground text-xs">
                {t("dashboards:filterBuilder.groupHint")}
              </p>
              {node.conditions.map((child, childIndex) => (
                <LeafRow
                  fields={fields}
                  // biome-ignore lint/suspicious/noArrayIndexKey: positional by design
                  key={childIndex}
                  leaf={child as FilterLeaf}
                  options={options}
                  onChange={(next) => {
                    const conditions = node.conditions.slice();
                    if (next === null) conditions.splice(childIndex, 1);
                    else conditions[childIndex] = next;
                    replaceAt(index, conditions.length ? { ...node, conditions } : null);
                  }}
                />
              ))}
              <Button
                size="sm"
                variant="ghost"
                onClick={() =>
                  replaceAt(index, { ...node, conditions: [...node.conditions, emptyLeaf()] })
                }
              >
                <Plus className="mr-1 h-3.5 w-3.5" />
                {t("dashboards:filterBuilder.add")}
              </Button>
            </div>
          ) : (
            <LeafRow
              leaf={node}
              fields={fields}
              options={options}
              onChange={(next) => replaceAt(index, next)}
            />
          )}
        </div>
      ))}

      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="outline" onClick={() => onChange([...value, emptyLeaf()])}>
          <Plus className="mr-1 h-3.5 w-3.5" />
          {t("dashboards:filterBuilder.add")}
        </Button>
        {!hasGroup && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => onChange([...value, { logic: "or", conditions: [emptyLeaf()] }])}
          >
            {t("dashboards:filterBuilder.addGroup")}
          </Button>
        )}
      </div>
    </div>
  );
}

type Options = {
  project: { value: string; label: string }[];
  tag: { value: string; label: string }[];
  member: { value: string; label: string }[];
};

function LeafRow({
  leaf,
  fields,
  options,
  onChange,
}: {
  leaf: FilterLeaf;
  fields: readonly FilterFieldSpec[];
  options: Options;
  onChange: (next: FilterLeaf | null) => void;
}) {
  const { t } = useTranslation(["dashboards", "common"]);
  const spec = fieldSpec(fields, leaf.field);

  const setField = (field: string) => {
    const next = fieldSpec(fields, field);
    // Changing the field drops the old value rather than carrying a set of tag
    // ids onto a date comparison.
    onChange({
      field,
      op: next?.ops[0] ?? "eq",
      value: next?.multiple ? [] : next?.kind === "date" ? { relative: 0 } : "",
    });
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <Select value={leaf.field} onValueChange={setField}>
          <SelectTrigger className="h-8 flex-1">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {fields.map((field) => (
              <SelectItem key={field.field} value={field.field}>
                {fieldLabel(field.field, t)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {(spec?.ops.length ?? 0) > 1 && (
          <Select value={leaf.op} onValueChange={(op) => onChange({ ...leaf, op: op as FilterOp })}>
            <SelectTrigger className="h-8 w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(spec?.ops ?? []).map((op) => (
                <SelectItem key={op} value={op}>
                  {t(`dashboards:filterOp.${op}` as const)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}

        <Button
          size="icon"
          variant="ghost"
          className="h-8 w-8 shrink-0"
          aria-label={t("dashboards:filterBuilder.remove")}
          onClick={() => onChange(null)}
        >
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>

      <ValueControl
        fields={fields}
        leaf={leaf}
        options={options}
        onChange={(value) => onChange({ ...leaf, value })}
      />
    </div>
  );
}

function ValueControl({
  leaf,
  fields,
  options,
  onChange,
}: {
  leaf: FilterLeaf;
  fields: readonly FilterFieldSpec[];
  options: Options;
  onChange: (value: ConditionValue) => void;
}) {
  const { t } = useTranslation(["dashboards", "tasks", "common"]);
  const spec = fieldSpec(fields, leaf.field);

  // "Is empty" compares against nothing, so there is nothing to choose.
  if (leaf.op === "is_null") return null;

  if (spec?.multiple) {
    const list = Array.isArray(leaf.value) ? leaf.value.map(String) : [];
    // A closed vocabulary carries its own values; everything else is a lookup
    // this screen already loads.
    const optionList =
      spec.kind === "select"
        ? (spec.options ?? []).map((value) => ({
            value,
            label: t(optionLabelKey(leaf.field, value), { defaultValue: value }),
          }))
        : spec.kind === "member"
          ? options.member
          : spec.kind === "tag"
            ? options.tag
            : [];
    return (
      <MultiSelect
        selectedValues={list}
        options={optionList}
        placeholder={t("dashboards:filterBuilder.chooseValue")}
        // Ids travel as numbers; "me" is the DSL's own token and stays a string.
        onChange={(values) =>
          onChange(values.map((value) => (value === "me" ? value : Number(value))))
        }
      />
    );
  }

  if (spec?.kind === "project") {
    return (
      <Select
        value={leaf.value ? String(leaf.value) : ""}
        onValueChange={(value) => onChange(Number(value))}
      >
        <SelectTrigger className="h-8">
          <SelectValue placeholder={t("dashboards:filterBuilder.chooseValue")} />
        </SelectTrigger>
        <SelectContent>
          {options.project.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    );
  }

  if (spec?.kind === "boolean") {
    return (
      <div className="flex items-center gap-2">
        <Switch checked={leaf.value === true} onCheckedChange={(checked) => onChange(checked)} />
        <span className="text-sm">{leaf.value === true ? t("common:yes") : t("common:no")}</span>
      </div>
    );
  }

  if (spec?.kind === "date") {
    const relative = isRelativeDate(leaf.value);
    return (
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Select
            value={relative ? "relative" : "absolute"}
            onValueChange={(mode) =>
              onChange(mode === "relative" ? { relative: 0 } : new Date().toISOString())
            }
          >
            <SelectTrigger className="h-8 w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="relative">{t("dashboards:filterBuilder.relative")}</SelectItem>
              <SelectItem value="absolute">{t("dashboards:filterBuilder.absolute")}</SelectItem>
            </SelectContent>
          </Select>

          {relative ? (
            <Input
              type="number"
              className="h-8"
              aria-label={t("dashboards:filterBuilder.relativeDays")}
              value={(leaf.value as { relative: number }).relative}
              onChange={(event) => onChange({ relative: Number(event.target.value) || 0 })}
            />
          ) : (
            <Input
              type="date"
              className="h-8"
              value={typeof leaf.value === "string" ? leaf.value.slice(0, 10) : ""}
              onChange={(event) =>
                onChange(new Date(`${event.target.value}T00:00:00Z`).toISOString())
              }
            />
          )}
        </div>
        {relative && (
          <p className="text-muted-foreground text-xs">
            {t("dashboards:filterBuilder.relativeHint")}
          </p>
        )}
      </div>
    );
  }

  return (
    <Input
      className="h-8"
      value={typeof leaf.value === "string" ? leaf.value : ""}
      placeholder={t("dashboards:filterBuilder.chooseValue")}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}
