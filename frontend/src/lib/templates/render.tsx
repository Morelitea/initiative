/**
 * Draw a compiled template as React elements.
 *
 * The one renderer, for Initiative's own theme (Tavern) and, later, for a
 * community's and for plug-in blocks. It creates elements and never sets HTML,
 * so a template can only ever produce the structure the compiler allowed.
 * Values that reach the page are held to what they may be when they arrive,
 * because a bound value is data the compiler never saw:
 *
 * - an `href` must lead somewhere inside the community, read as the browser
 *   will read it, and becomes a router link;
 * - a `src` must be one of the community's uploads, read the same way, and is
 *   addressed as every upload is (`resolveUploadUrl`);
 * - a `:style` sets custom properties only, each a number, a length, a colour
 *   or a keyword, so nothing from a row is ever read as CSS.
 *
 * A `for` stops repeating once one render has drawn MAX_RENDERED_NODES
 * elements and text runs, however long its list. Nothing outside a loop is
 * ever cut.
 */

import { Link } from "@tanstack/react-router";
import { type ComponentType, createElement, Fragment, type ReactNode } from "react";

import { resolveUploadUrl } from "@/lib/uploadUrl";

import type { CompiledNode, CompiledTemplate } from "./compile";
import { bindings, evaluate } from "./runtime";

export interface RenderInput {
  /** The section's data, by the names its template reads. */
  data: Record<string, unknown>;
  /** What the route shares with every part, passed through untouched. */
  context: unknown;
  parts: Readonly<Record<string, ComponentType<{ data: never; context: never }>>>;
  /** The community the screen belongs to: links and pictures stay inside it. */
  communityId: number;
  /** Parts the member has turned off, drawn as nothing wherever the template places them. */
  hidden?: ReadonlySet<string>;
  /** The components a template may place, such as a widget's charts, by element name. */
  elements?: Readonly<Record<string, ComponentType<{ props: Record<string, unknown> }>>>;
}

type Scope = Record<string, unknown>;

/** A custom property's value: a number, a length, a hex colour or a keyword. */
const STYLE_VALUE = /^(-?\d+(\.\d+)?(px|rem|em|%|ch)?|#[0-9a-f]{3,8}|[a-z][a-z-]*)$/i;

const REACT_NAMES: Record<string, string> = { class: "className", datetime: "dateTime" };

export const MAX_RENDERED_NODES = 2000;

/**
 * Each template's answers outside any loop, by the data they were worked out
 * from. A route's data does not change in place (a changed row is a new
 * object), so while it passes the same data object, a render reuses them. An
 * answer from a display function is never kept: it depends on the reader too.
 */
const answers = new WeakMap<CompiledTemplate, WeakMap<object, unknown[]>>();

/** Any address resolves against this, so only a path on our own origin comes back out. */
const ORIGIN = "https://community.invalid";

/**
 * `value` as the path the browser would request, when that path is under
 * `prefix`; null otherwise. Dot segments, encoded or not, are resolved first.
 */
const within = (value: unknown, prefix: string): string | null => {
  if (typeof value !== "string") return null;
  let url: URL;
  try {
    url = new URL(value, `${ORIGIN}/`);
  } catch {
    return null;
  }
  if (url.origin !== ORIGIN || !url.pathname.startsWith(prefix)) return null;
  return url.pathname + url.search + url.hash;
};

const text = (value: unknown): string => {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "bigint") return String(value);
  return "";
};

/** An attribute's value; true and false stay words, as ARIA states need them. */
const attribute = (value: unknown): string =>
  typeof value === "boolean" ? String(value) : text(value);

const classes = (value: unknown): string => {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map(classes).filter(Boolean).join(" ");
  if (value && typeof value === "object") {
    return Object.entries(value)
      .filter(([, on]) => on === true)
      .map(([name]) => name)
      .join(" ");
  }
  return "";
};

const style = (value: unknown): Record<string, string> | undefined => {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const properties: Record<string, string> = {};
  for (const [name, raw] of Object.entries(value)) {
    const plain = typeof raw === "number" ? String(raw) : raw;
    if (name.startsWith("--") && typeof plain === "string" && STYLE_VALUE.test(plain)) {
      properties[name] = plain;
    }
  }
  return properties;
};

export function renderTemplate(template: CompiledTemplate, input: RenderInput): ReactNode {
  const linkPrefix = `/c/${input.communityId}/`;
  const uploadPrefix = `/uploads/${input.communityId}/`;

  const root = bindings(input.data);
  const byData = answers.get(template) ?? new WeakMap<object, unknown[]>();
  answers.set(template, byData);
  const kept = byData.get(input.data) ?? [];
  byData.set(input.data, kept);

  const value = (index: number, scope: Scope) => {
    if (scope !== root || template.display.includes(index)) {
      return evaluate(template.exprs[index] as string, scope);
    }
    if (!(index in kept)) kept[index] = evaluate(template.exprs[index] as string, scope);
    return kept[index];
  };

  const props = (
    attrs: Record<string, string>,
    bind: Record<string, number>,
    scope: Scope
  ): Record<string, unknown> => {
    const out: Record<string, unknown> = {};
    for (const [name, raw] of Object.entries(attrs)) out[REACT_NAMES[name] ?? name] = raw;
    for (const [name, index] of Object.entries(bind)) {
      const bound = value(index, scope);
      if (name === "class") {
        out.className = [attrs.class, classes(bound)].filter(Boolean).join(" ");
      } else if (name === "style") {
        out.style = style(bound);
      } else {
        out[REACT_NAMES[name] ?? name] = attribute(bound);
      }
    }
    if ("href" in out) {
      const href = within(out.href, linkPrefix);
      if (href) out.href = href;
      else delete out.href;
    }
    if ("src" in out) {
      const src = resolveUploadUrl(within(out.src, uploadPrefix));
      if (src) out.src = src;
      else delete out.src;
    }
    return out;
  };

  let drawn = 0;

  const draw = (node: CompiledNode, scope: Scope, key: string | number): ReactNode => {
    if (node.t === "text" || node.t === "el" || node.t === "part" || node.t === "component") {
      drawn++;
    }
    switch (node.t) {
      case "text":
        return node.parts.map((part) =>
          typeof part === "string" ? part : text(value(part, scope))
        );
      case "el": {
        const elementProps: Record<string, unknown> = {
          ...props(node.attrs, node.bind, scope),
          key,
        };
        const kids = node.kids.map((kid, index) => draw(kid, scope, index));
        if (node.tag === "a") {
          const { href, ...rest } = elementProps;
          if (typeof href !== "string") return createElement("span", rest, ...kids);
          return createElement(Link, { ...rest, to: href } as never, ...kids);
        }
        if (node.tag === "img" && !("src" in elementProps)) return null;
        return createElement(node.tag, elementProps, ...kids);
      }
      case "part": {
        const Part = input.parts[node.name];
        if (!Part || input.hidden?.has(node.name)) return null;
        // No element of its own: the template's classes go to the part's.
        const { className } = props(node.attrs, node.bind, scope);
        return createElement(Part, {
          key,
          data: input.data,
          context: input.context,
          className,
        } as never);
      }
      case "component": {
        const Component = input.elements?.[node.name];
        if (!Component) return null;
        // As the template gave them: a bound value goes on as data, not as text.
        const values: Record<string, unknown> = { ...node.attrs };
        for (const [name, index] of Object.entries(node.bind)) values[name] = value(index, scope);
        return createElement(Component, { key, props: values });
      }
      case "if": {
        for (const branch of node.branches) {
          if (branch.when === null || value(branch.when, scope) === true) {
            return draw(branch.node, scope, key);
          }
        }
        return null;
      }
      case "for": {
        const list = value(node.list, scope);
        if (!Array.isArray(list)) return null;
        // Only a loop's repeats are cut short. Everything outside loops always
        // draws, required parts included, since none may sit inside a for.
        const items: ReactNode[] = [];
        for (const [index, item] of list.entries()) {
          if (drawn >= MAX_RENDERED_NODES) break;
          items.push(draw(node.node, { ...scope, [node.item]: item }, index));
        }
        return createElement(Fragment, { key }, items);
      }
    }
  };

  return template.root.map((node, index) => draw(node, root, index));
}
