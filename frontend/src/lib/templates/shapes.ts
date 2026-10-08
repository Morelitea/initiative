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

const SCHEMAS = schemaShapes as unknown as Record<string, Shape>;

/** A schema by name, or undefined when the spec has no such schema. */
export function schemaShape(name: string): Shape | undefined {
  return SCHEMAS[name];
}

/** Follow references until the shape says what it holds. */
export function resolveShape(shape: Shape): Shape {
  let current = shape;
  for (let hops = 0; typeof current === "object" && "ref" in current; hops++) {
    if (hops > 32) return "any";
    current = SCHEMAS[current.ref] ?? "any";
  }
  return current;
}

/**
 * The shape of `field` on a value of `shape`: a shape, "any" when the value is
 * a map or not known, or undefined when it is a record with no such field.
 */
export function fieldShape(shape: Shape, field: string): Shape | undefined {
  const resolved = resolveShape(shape);
  if (resolved === "any") return "any";
  if (typeof resolved !== "object") return undefined;
  if ("fields" in resolved) return resolved.fields[field];
  if ("map" in resolved) return resolved.map;
  return undefined;
}

/** The shape of one item of a list, or "any" when it is not known to be a list. */
export function itemShape(shape: Shape): Shape {
  const resolved = resolveShape(shape);
  if (typeof resolved === "object" && "list" in resolved) return resolved.list;
  return "any";
}
