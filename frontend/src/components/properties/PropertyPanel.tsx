import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  PropertyDefinitionRead,
  PropertySummary,
  PropertyTarget,
} from "@/api/generated/initiativeAPI.schemas";
import { useSetProperties } from "@/hooks/useProperties";

import { AddPropertyButton } from "./AddPropertyButton";
import {
  PropertyFields,
  type PropertyFieldsProps,
  propertyStubFromDefinition,
} from "./PropertyFields";
import { normalizePropertyValue } from "./propertyHelpers";

const NONE: PropertySummary[] = [];

const SAVE_DEBOUNCE_MS = 400;

export interface PropertyPanelProps {
  target: PropertyTarget;
  entityId: number;
  /** The row's properties as the server last sent them. */
  saved: PropertySummary[] | undefined;
  /** The initiative whose definitions may be added. */
  initiativeId: number;
  canOpen?: PropertyFieldsProps["canOpen"];
  disabled?: boolean;
}

/** What the row shows beyond the server's copy: properties just added, ones
 *  just removed, and every value as it is being edited. */
interface Local {
  added: PropertySummary[];
  removed: ReadonlySet<number>;
  values: Record<number, unknown>;
}

const valuesOf = (properties: PropertySummary[]) =>
  Object.fromEntries(properties.map((p) => [p.property_id, normalizePropertyValue(p)]));

/**
 * The properties on one tool or sub-tool, and the button that adds another.
 * Every change is saved on its own, a moment after the last one, so it needs
 * no Save button.
 *
 * Keyed by the row: a host that stays on screen while it moves to another row
 * (a wiki page's drawer, a document opened from a document) gets a fresh one,
 * so one row's edits and additions never reach the next.
 */
export const PropertyPanel = (props: PropertyPanelProps) => (
  <RowProperties key={`${props.target}:${props.entityId}`} {...props} />
);

const RowProperties = ({
  target,
  entityId,
  saved = NONE,
  initiativeId,
  canOpen,
  disabled = false,
}: PropertyPanelProps) => {
  const { t } = useTranslation("properties");
  const { mutate, isPending } = useSetProperties();

  const [local, setLocal] = useState<Local>(() => ({
    added: [],
    removed: new Set(),
    values: valuesOf(saved),
  }));
  // Properties changed since the last write settled. A copy of the row from
  // the server leaves their values alone, since it predates the change.
  const changing = useRef(new Set<number>());

  // The server's copy moved on: what it now holds is no longer pending, and
  // every value nobody is changing is taken from it.
  useEffect(() => {
    const ids = new Set(saved.map((p) => p.property_id));
    setLocal((prev) => {
      const added = prev.added.filter((p) => !ids.has(p.property_id));
      const removed = new Set([...prev.removed].filter((id) => ids.has(id)));
      const values: Record<number, unknown> = {};
      for (const p of added) values[p.property_id] = prev.values[p.property_id];
      for (const p of saved) {
        values[p.property_id] = changing.current.has(p.property_id)
          ? prev.values[p.property_id]
          : normalizePropertyValue(p);
      }
      return { added, removed, values };
    });
  }, [saved]);

  const shown = useMemo(
    () => [...saved, ...local.added].filter((p) => !local.removed.has(p.property_id)),
    [saved, local]
  );

  // Read when the write goes, not when it is scheduled, so it carries
  // everything changed in the meantime.
  const latest = useRef(shown);
  latest.current = shown;
  const latestValues = useRef(local.values);
  latestValues.current = local.values;

  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // The write waiting out the pause, if any. Sent rather than dropped when
  // the panel goes (a dialog closed straight after typing): it holds this
  // row's own values, so it is still the right write.
  const pendingWrite = useRef<(() => void) | null>(null);

  const scheduleSave = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    pendingWrite.current = () => {
      pendingWrite.current = null;
      // Replace-all: every property the row keeps is sent, empty or not, so
      // one added without a value stays attached.
      const values = latest.current.map((p) => ({
        property_id: p.property_id,
        value:
          p.property_id in latestValues.current
            ? (latestValues.current[p.property_id] ?? null)
            : (normalizePropertyValue(p) ?? null),
      }));
      mutate({ target, id: entityId, values }, { onSettled: () => changing.current.clear() });
    };
    timer.current = setTimeout(() => {
      timer.current = null;
      pendingWrite.current?.();
    }, SAVE_DEBOUNCE_MS);
  }, [target, entityId, mutate]);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
      pendingWrite.current?.();
    },
    []
  );

  const change = useCallback(
    (propertyId: number, value: unknown) => {
      changing.current.add(propertyId);
      setLocal((prev) => ({ ...prev, values: { ...prev.values, [propertyId]: value } }));
      scheduleSave();
    },
    [scheduleSave]
  );

  const remove = useCallback(
    (propertyId: number) => {
      changing.current.add(propertyId);
      setLocal((prev) => ({
        ...prev,
        added: prev.added.filter((p) => p.property_id !== propertyId),
        removed: new Set(prev.removed).add(propertyId),
      }));
      scheduleSave();
    },
    [scheduleSave]
  );

  const add = useCallback(
    (definition: PropertyDefinitionRead) => {
      if (latest.current.some((p) => p.property_id === definition.id)) return;
      changing.current.add(definition.id);
      setLocal((prev) => {
        const removed = new Set(prev.removed);
        removed.delete(definition.id);
        const onServer = saved.some((p) => p.property_id === definition.id);
        return {
          added: onServer ? prev.added : [...prev.added, propertyStubFromDefinition(definition)],
          removed,
          values: { ...prev.values, [definition.id]: null },
        };
      });
      scheduleSave();
    },
    [saved, scheduleSave]
  );

  return (
    <div className="space-y-3">
      <div className="space-y-2">
        <PropertyFields
          properties={shown}
          values={local.values}
          onChange={change}
          onRemove={remove}
          disabled={disabled}
          initiativeId={initiativeId}
          canOpen={canOpen}
        />
        {isPending ? <p className="text-muted-foreground text-xs">{t("saving")}</p> : null}
      </div>
      <AddPropertyButton
        initiativeId={initiativeId}
        currentPropertyIds={shown.map((p) => p.property_id)}
        onAdd={add}
        disabled={disabled}
      />
    </div>
  );
};
