#!/usr/bin/env node
/**
 * Write `src/api/generated/schemaShapes.json` from the OpenAPI spec.
 *
 * The template compiler checks every field a template reads against the data
 * its section is given, and that data is an API response. This is the same
 * spec Orval generates the TypeScript types from, reduced to what a field
 * check needs: each schema's fields and what each one holds. It is generated
 * beside the types, so the codegen check holds it to the backend as it holds
 * them.
 *
 *   node scripts/build-schema-shapes.mjs openapi.json
 */

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const specPath = process.argv[2] ?? join(here, "..", "openapi.json");
const outPath = join(here, "..", "src", "api", "generated", "schemaShapes.json");

const spec = JSON.parse(readFileSync(specPath, "utf-8"));
const schemas = spec.components?.schemas ?? {};

const refName = (ref) => ref.slice(ref.lastIndexOf("/") + 1);

/** What one schema node holds: a scalar kind, a reference, a list or a map. */
function shapeOf(node) {
  if (!node || typeof node !== "object") return "any";
  if (node.$ref) return { ref: refName(node.$ref) };
  // `X | null` is X: a template compares against null like any other value.
  const options = (node.anyOf ?? node.oneOf ?? []).filter((option) => option.type !== "null");
  if (options.length === 1) return shapeOf(options[0]);
  if (options.length > 1) return "any";
  if (node.allOf?.length === 1) return shapeOf(node.allOf[0]);
  if (Array.isArray(node.enum)) return { enum: node.enum.filter((value) => value !== null) };
  switch (node.type) {
    case "string":
      return "string";
    case "integer":
    case "number":
      return "number";
    case "boolean":
      return "boolean";
    case "array":
      return { list: shapeOf(node.items) };
    case "object":
      if (node.properties) return { fields: fieldsOf(node) };
      return { map: shapeOf(node.additionalProperties) };
    default:
      return "any";
  }
}

function fieldsOf(node) {
  const fields = {};
  for (const [name, field] of Object.entries(node.properties ?? {})) fields[name] = shapeOf(field);
  return fields;
}

const shapes = {};
for (const name of Object.keys(schemas).sort()) shapes[name] = shapeOf(schemas[name]);

writeFileSync(outPath, `${JSON.stringify(shapes)}\n`);
