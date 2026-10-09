/**
 * What the data a template reads holds, field by field.
 *
 * Derived from the same OpenAPI spec as the generated API types
 * (`scripts/build-schema-shapes.mjs` writes `schemaShapes.json` beside them), so
 * a field the backend renames fails the template that reads it at the next
 * `pnpm generate:api`, in the change that renamed it.
 */

import schemaShapes from "../../api/generated/schemaShapes.json" with { type: "json" };

export type Shape =
  | "string"
  | "number"
  | "boolean"
  | "any"
  | { ref: string }
  | { list: Shape }
  | { map: Shape }
  | { fields: Record<string, Shape> }
  | { enum: Array<string | number | boolean> };

/** Schemas by name. */
export type ShapeTable = Readonly<Record<string, Shape>>;

/** The schemas the sections read, and everything they reference. */
export const SCHEMA_SHAPES = schemaShapes as unknown as ShapeTable;

/** Follow references until the shape says what it holds. */
export function resolveShape(shape: Shape, table: ShapeTable = SCHEMA_SHAPES): Shape {
  let current = shape;
  for (let hops = 0; typeof current === "object" && "ref" in current; hops++) {
    if (hops > 32) return "any";
    current = table[current.ref] ?? "any";
  }
  return current;
}

/**
 * The shape of `field` on a value of `shape`: a shape, "any" when the value is
 * a map or not known, or undefined when it is a record with no such field.
 */
export function fieldShape(
  shape: Shape,
  field: string,
  table: ShapeTable = SCHEMA_SHAPES
): Shape | undefined {
  const resolved = resolveShape(shape, table);
  if (resolved === "any") return "any";
  if (typeof resolved !== "object") return undefined;
  if ("fields" in resolved) return resolved.fields[field];
  if ("map" in resolved) return resolved.map;
  return undefined;
}

/** The shape of one item of a list, or "any" when it is not known to be a list. */
export function itemShape(shape: Shape, table: ShapeTable = SCHEMA_SHAPES): Shape {
  const resolved = resolveShape(shape, table);
  if (typeof resolved === "object" && "list" in resolved) return resolved.list;
  return "any";
}
