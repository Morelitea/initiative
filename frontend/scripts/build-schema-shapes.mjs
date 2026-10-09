#!/usr/bin/env node
/**
 * Write `src/api/generated/initiativeAPI.shapes.json` from the OpenAPI spec.
 *
 * The template compiler checks every field a template reads against the data
 * its section is given, and that data is an API response. This is the same
 * spec Orval generates the TypeScript types from, reduced to what a field
 * check needs: each schema's fields and what each one holds. It is generated
 * beside the types, so the codegen check holds it to the backend as it holds
 * them.
 *
 * Only the schemas a section reads are written, with everything they
 * reference: the registry (src/lib/templates/sections.ts) names them, so a
 * schema no template can reach never appears here or changes it. It reads the
 * spec Orval reads, so it holds nothing the generated client does not.
 *
 * Orval runs it after writing the client (`afterAllFilesWrite` in
 * orval.config.ts), so `pnpm generate:api` and the codegen check regenerate it
 * with the types. The flag lets Node 22 read the registry's TypeScript; Node 24
 * needs none.
 */

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { SECTIONS } from "../src/lib/templates/sections.ts";

const here = dirname(fileURLToPath(import.meta.url));
const specPath = process.argv[2] ?? join(here, "..", "openapi.json");
const outPath = join(here, "..", "src", "api", "generated", "initiativeAPI.shapes.json");

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

/** Every schema `shape` names, at any depth. */
function referencesOf(shape, found = []) {
  if (shape && typeof shape === "object") {
    if (shape.ref) found.push(shape.ref);
    for (const inner of Object.values(shape)) referencesOf(inner, found);
  }
  return found;
}

const shapes = {};
const pending = Object.values(SECTIONS).flatMap((section) => Object.values(section.data));
while (pending.length > 0) {
  const name = pending.pop();
  if (name in shapes || !(name in schemas)) continue;
  shapes[name] = shapeOf(schemas[name]);
  pending.push(...referencesOf(shapes[name]));
}
const sorted = Object.fromEntries(
  Object.keys(shapes)
    .sort()
    .map((name) => [name, shapes[name]])
);

writeFileSync(outPath, `${JSON.stringify(sorted)}\n`);
