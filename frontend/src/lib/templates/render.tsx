/**
 * Draw a compiled template as React elements.
 *
 * The one renderer, for Initiative's own theme (Tavern) and, later, for a
 * community's and for plug-in blocks. It creates elements and never sets HTML,
 * so a template can only ever produce the structure the compiler allowed.
 * Values that reach the page are held to what they may be when they arrive,
 * because a bound value is data the compiler never saw:
 *
 * - an `href` must lead somewhere inside the community, and becomes a router
 *   link;
 * - a `src` must be one of the community's uploads;
 * - a `:style` sets custom properties only, each a number, a length, a colour
 *   or a keyword, so nothing from a row is ever read as CSS.
 */

import { Link } from "@tanstack/react-router";
import { type ComponentType, createElement, Fragment, type ReactNode } from "react";

import type { CompiledNode, CompiledTemplate } from "./compile";
import { evaluate } from "./runtime";

export interface RenderInput {
  /** The section's data, by the names its template reads. */
  data: Record<string, unknown>;
  /** What the route shares with every part, passed through untouched. */
  context: unknown;
  parts: Readonly<Record<string, ComponentType<{ data: never; context: never }>>>;
  /** The community the screen belongs to: links and pictures stay inside it. */
  communityId: number;
}

type Scope = Record<string, unknown>;

/** A custom property's value: a number, a length, a hex colour or a keyword. */
const STYLE_VALUE = /^(-?\d+(\.\d+)?(px|rem|em|%|ch)?|#[0-9a-f]{3,8}|[a-z][a-z-]*)$/i;

const REACT_NAMES: Record<string, string> = { class: "className", datetime: "dateTime" };

const text = (value: unknown): string => {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "bigint") return String(value);
  return "";
};

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

  const value = (index: number, scope: Scope) => evaluate(template.exprs[index] as string, scope);

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
        out[REACT_NAMES[name] ?? name] = text(bound);
      }
    }
    if ("href" in out && !String(out.href).startsWith(linkPrefix)) delete out.href;
    if ("src" in out && !String(out.src).startsWith(uploadPrefix)) delete out.src;
    return out;
  };

  const draw = (node: CompiledNode, scope: Scope, key: string | number): ReactNode => {
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
        if (!Part) return null;
        return createElement(
          "div",
          { ...props(node.attrs, node.bind, scope), key, "data-part": node.name },
          createElement(Part, { data: input.data, context: input.context } as never)
        );
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
        return createElement(
          Fragment,
          { key },
          list.map((item, index) => draw(node.node, { ...scope, [node.item]: item }, index))
        );
      }
    }
  };

  return template.root.map((node, index) => draw(node, input.data, index));
}
