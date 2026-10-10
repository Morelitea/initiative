/**
 * Field editors any item's page shares (a task's, an event's): the title, the
 * tags and the custom properties, each saved on its own through the save of
 * the item's kind.
 */

import { X } from "lucide-react";
import { useTranslation } from "react-i18next";

import type {
  PropertyDefinitionRead,
  PropertySummary,
  TagSummary,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { AddPropertyButton } from "@/components/properties/AddPropertyButton";
import { propertyStubFromDefinition } from "@/components/properties/PropertyFields";
import { PropertyInput } from "@/components/properties/PropertyInput";
import {
  isEmptyPropertyValue,
  normalizePropertyValue,
  userReferenceValue,
} from "@/components/properties/propertyHelpers";
import { TagPicker } from "@/components/tags";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  type FieldSaveKind,
  type ItemEdit,
  type ItemFieldSave,
  useItemFieldSave,
} from "@/hooks/useFieldSave";

import { FieldFrame, useFieldDraft } from "./editing";

const sameJson = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/** An item's title, which is its page's heading. It cannot be emptied:
 *  leaving it blank puts the saved one back. */
export const TitleField = <I extends { title: string }, P extends { title?: string | null }>({
  id,
  label,
  value,
  save,
  readOnly,
  placeholder,
}: {
  id: string;
  label: string;
  value: string;
  save: ItemFieldSave<I, P>;
  readOnly: boolean;
  placeholder: string;
}) => {
  const draft = useFieldDraft(value, async (title) =>
    title.trim() ? save.save({ patch: { title } as P, shows: { title } as Partial<I> }) : false
  );
  return (
    <FieldFrame
      label={label}
      htmlFor={id}
      hideLabel
      statusBelow
      save={save}
      changed={draft.changed}
      keys={draft.keys}
      className="flex-1"
    >
      <h1 className="sr-only">{value}</h1>
      <Input
        id={id}
        value={draft.value}
        onChange={(event) => draft.change(event.target.value)}
        placeholder={placeholder}
        disabled={readOnly}
        className="h-auto font-semibold text-3xl tracking-tight shadow-none focus-visible:ring-0 sm:text-3xl"
      />
    </FieldFrame>
  );
};

/** An item's tags, saved the moment they are picked. Clearing them offers
 *  Undo. */
export const TagsField = <
  I extends { tags: TagSummary[] },
  P extends { tag_ids?: number[] | null },
>({
  label,
  tags,
  save,
  readOnly,
  placeholder,
}: {
  label: string;
  tags: TagSummary[];
  save: ItemFieldSave<I, P>;
  readOnly: boolean;
  placeholder: string;
}) => {
  const edit = (picked: TagSummary[]): ItemEdit<I, P> => ({
    patch: { tag_ids: picked.map((tag) => tag.id) } as P,
    shows: { tags: picked } as Partial<I>,
  });
  return (
    <FieldFrame label={label} save={save}>
      <TagPicker
        selectedTags={tags}
        onChange={(picked) =>
          void save.save(edit(picked), picked.length === 0 ? edit(tags) : undefined)
        }
        disabled={readOnly}
        placeholder={placeholder}
      />
    </FieldFrame>
  );
};

/** What the properties of an item take: its kind's save, the item, and who
 *  a person-valued property may name. */
type PropertiesProps<I extends { properties: PropertySummary[] }, P> = {
  kind: FieldSaveKind<I, P>;
  id: number;
  properties: PropertySummary[];
  readOnly: boolean;
  initiativeId: number | null;
  /** Whose people a person-valued property may name: who can open this tool. */
  canOpen: { tool: Tool; id: number | null | undefined };
};

/** How a value reads on the item until the server says: a person's own
 *  summary while they are still the one named. */
const showing = (property: PropertySummary, value: unknown): PropertySummary => ({
  ...property,
  value: value === normalizePropertyValue(property) ? property.value : value,
});

/** One custom property, saved on its own as its kind says. Only it is sent,
 *  so a change to another property meanwhile still stands. */
const PropertyField = <I extends { properties: PropertySummary[] }, P>({
  kind,
  id,
  properties,
  readOnly,
  initiativeId,
  canOpen,
  property,
}: PropertiesProps<I, P> & { property: PropertySummary }) => {
  const { t } = useTranslation("properties");
  const save = useItemFieldSave(kind, id, property.name);
  const saved = normalizePropertyValue(property);
  const edit = (value: unknown): ItemEdit<I, P> => ({
    properties: { values: [{ property_id: property.property_id, value }] },
    shows: {
      properties: properties.map((p) =>
        p.property_id === property.property_id ? showing(p, value) : p
      ),
    } as Partial<I>,
  });
  const draft = useFieldDraft(
    saved,
    (value) =>
      save.save(
        edit(value),
        isEmptyPropertyValue(value) && !isEmptyPropertyValue(saved) ? edit(saved) : undefined
      ),
    sameJson
  );
  // The property stays until it is gone, so a failed removal says so here.
  const remove = () => {
    draft.restore();
    void save.save(
      { properties: { values: [], removed: [property.property_id] }, shows: {} },
      { ...edit(saved), shows: { properties } as Partial<I> }
    );
  };
  return (
    <FieldFrame
      label={property.name}
      save={save}
      changed={draft.changed}
      keys={draft.keys}
      action={
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          className="text-muted-foreground"
          onClick={remove}
          disabled={readOnly}
          aria-label={t("remove")}
        >
          <X className="h-4 w-4" />
        </Button>
      }
    >
      <PropertyInput
        definition={property}
        value={draft.value}
        onChange={draft.edit}
        disabled={readOnly}
        initiativeId={initiativeId}
        canOpen={canOpen}
        selectedUser={userReferenceValue(property)}
      />
    </FieldFrame>
  );
};

/** An item's custom properties, each saved on its own, and adding one. */
export const PropertiesField = <I extends { properties: PropertySummary[] }, P>(
  props: PropertiesProps<I, P>
) => {
  const { t } = useTranslation("properties");
  const { kind, id, properties, readOnly, initiativeId } = props;
  const label = t("title");
  const save = useItemFieldSave(kind, id, label);
  const add = (definition: PropertyDefinitionRead) => {
    if (properties.some((p) => p.property_id === definition.id)) return;
    void save.save({
      properties: { values: [{ property_id: definition.id, value: null }] },
      shows: {
        properties: [...properties, propertyStubFromDefinition(definition)],
      } as Partial<I>,
    });
  };
  const sorted = [...properties].sort((a, b) => a.name.localeCompare(b.name));
  return (
    <FieldFrame label={label} save={save}>
      {sorted.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("noProperties")}</p>
      ) : (
        sorted.map((property) => (
          <PropertyField key={property.property_id} {...props} property={property} />
        ))
      )}
      <AddPropertyButton
        initiativeId={initiativeId ?? 0}
        currentPropertyIds={properties.map((p) => p.property_id)}
        onAdd={add}
        disabled={readOnly || !initiativeId}
      />
    </FieldFrame>
  );
};
