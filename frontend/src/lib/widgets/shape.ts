/**
 * Which of a query's columns fill a widget's slots.
 *
 * A widget declares the shape it draws — a chart a label and one or more
 * numbers, a gantt a label and two dates — and any query returning that shape
 * drives it. What decides *which* column is which is here, and it is inference
 * first: a dashboard whose every tile has to be wired column by column is a
 * worse dashboard than one that guesses well and lets you correct it.
 *
 * Three rules, in order:
 *
 * 1. **A stored mapping wins.** The author already answered.
 * 2. **Otherwise take the first column that fits**, walking the slots in the
 *    order the widget declared them and never using one column twice.
 * 3. **A widget whose required slots cannot all be filled draws nothing** —
 *    the caller offers the table instead, which draws any shape by
 *    construction. A shape that fits nothing is never an error.
 */

import type { WidgetSlot } from "@/api/generated/initiativeAPI.schemas";
import type { DataColumn } from "@/lib/widgets/dataShapes";

export type SlotMapping = Record<string, number[]>;

/** Whether this column could fill this slot. */
const fits = (column: DataColumn, slot: WidgetSlot): boolean =>
  (slot.types as string[]).includes(column.type);

/**
 * The mapping to render with: what the author stored, and inference for the
 * rest.
 *
 * Stored ordinals are honoured even when they no longer fit — a query edited
 * under a saved widget is the author's to reconcile, and silently repointing
 * their chart at a different column would hide that it needs attention. Only an
 * ordinal that has fallen off the end of the row is dropped, because there is
 * nothing there to read.
 */
export const resolveMapping = (
  columns: DataColumn[],
  shape: WidgetSlot[],
  stored?: SlotMapping | null
): SlotMapping => {
  const mapping: SlotMapping = {};
  const taken = new Set<number>();

  for (const slot of shape) {
    const held = (stored?.[slot.name] ?? []).filter((index) => index < columns.length);
    if (held.length) {
      mapping[slot.name] = held;
      for (const index of held) taken.add(index);
    }
  }

  for (const slot of shape) {
    if (mapping[slot.name]) continue;
    const found: number[] = [];
    for (let index = 0; index < columns.length; index++) {
      if (taken.has(index) || !fits(columns[index], slot)) continue;
      found.push(index);
      taken.add(index);
      if (!slot.repeatable) break;
    }
    if (found.length) mapping[slot.name] = found;
  }
  return mapping;
};

/** Whether a widget can draw these columns at all — every required slot filled.
 *  A widget declaring no shape draws anything, which is what makes the table
 *  the fallback. */
export const canDraw = (
  columns: DataColumn[],
  shape: WidgetSlot[],
  stored?: SlotMapping | null
): boolean => {
  if (!shape.length) return true;
  const mapping = resolveMapping(columns, shape, stored);
  return shape.every((slot) => !slot.required || mapping[slot.name]?.length);
};

/** The columns a slot may be pointed at, for the picker that overrides
 *  inference. Offered by *ordinal*, because two columns may share a name. */
export const candidatesFor = (columns: DataColumn[], slot: WidgetSlot): number[] =>
  columns.flatMap((column, index) => (fits(column, slot) ? [index] : []));
