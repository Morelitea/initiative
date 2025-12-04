import type { SortingFn } from "@tanstack/react-table";

const toTimestamp = (value: unknown): number | null => {
  if (!value) {
    return null;
  }

  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value.getTime();
  }

  if (typeof value === "string" || typeof value === "number") {
    const date = new Date(value);
    const time = date.getTime();
    return Number.isNaN(time) ? null : time;
  }

  return null;
};

/**
 * Sorts nullable date-ish values while keeping undated rows at the bottom.
 */
export const dateSortingFn: SortingFn<unknown> = (rowA, rowB, columnId) => {
  const valueA = toTimestamp(rowA.getValue(columnId));
  const valueB = toTimestamp(rowB.getValue(columnId));

  if (valueA === valueB) {
    return 0;
  }

  if (valueA === null) {
    return 1;
  }

  if (valueB === null) {
    return -1;
  }

  return valueA - valueB;
};
