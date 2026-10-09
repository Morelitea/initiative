/**
 * Compile a template into the tree the renderer draws.
 *
 * The one compiler: the Vite plugin runs it on Tavern's files, and later the
 * browser runs it on an admin's draft and the server's V8 on a saved theme. It
 * holds a template to what a community screen may contain:
 *
 * - an allowlist of elements and attributes, so markup can only be structure
 *   and text, never script, forms or frames;
 * - our own `<part>`, placing one of the section's components;
 * - directives on whole elements (`if`, `else-if`, `else`, `for`, `:attr`) and
 *   `{{ }}` in text, every expression checked by expressions.ts;
 * - every required part exactly once, outside any `if` or `for`.
 *
 * The result is plain data: the renderer turns it into React elements and never
 * into an HTML string.
 *
 * Kept free of the browser and of `@/` imports, and its own imports name their
 * `.ts` files: the Vite plugin runs it in Node.
 */

import type { WidgetElementDefinition } from "../widgets/elements.ts";
import { checkExpression, type ExpressionScope } from "./expressions.ts";
import {
  parseTemplate,
  type SourcePosition,
  type TemplateAttribute,
  type TemplateElement,
  TemplateError,
  type TemplateNode,
} from "./parse.ts";
import type { SectionDefinition } from "./sections.ts";
import { itemShape, type Shape, schemaShape } from "./shapes.ts";

export type CompiledNode =
  | {
      t: "el";
      tag: string;
      attrs: Record<string, string>;
      /** Attribute name → index into `exprs`. */
      bind: Record<string, number>;
      kids: CompiledNode[];
    }
  | { t: "text"; parts: Array<string | number> }
  | { t: "part"; name: string; attrs: Record<string, string>; bind: Record<string, number> }
  /** One of our components, drawn from the props the template gives it. */
  | { t: "component"; name: string; attrs: Record<string, string>; bind: Record<string, number> }
  | { t: "if"; branches: Array<{ when: number | null; node: CompiledNode }> }
  | { t: "for"; item: string; list: number; node: CompiledNode };

export interface CompiledTemplate {
  section: string;
  /** Every expression's source, once; the renderer plans each once. */
  exprs: string[];
  /**
   * The expressions that call a display function. Their answers depend on the
   * reader's language and settings, so the renderer never reuses one.
   */
  display: number[];
  root: CompiledNode[];
}

/** Structure and text, and nothing that runs, submits or frames. */
const ELEMENTS = new Set([
  "div",
  "span",
  "p",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "section",
  "header",
  "footer",
  "article",
  "ul",
  "ol",
  "li",
  "strong",
  "em",
  "small",
  "time",
  "figure",
  "hr",
  "br",
  "img",
  "a",
]);

/** Attributes any element may carry, as given or bound. */
const GLOBAL_ATTRIBUTES = new Set(["class", "title"]);
const ELEMENT_ATTRIBUTES: Record<string, Set<string>> = {
  img: new Set(["src", "alt"]),
  a: new Set(["href"]),
  time: new Set(["datetime"]),
};
/** Only ever bound: a map of custom properties, typed when rendered. */
const BOUND_ONLY = new Set(["style"]);
/** Initiative's own, for marking sections and parts; a template never sets them. */
const RESERVED_DATA = new Set(["data-section", "data-part", "data-node"]);

const DIRECTIVES = new Set(["if", "else-if", "else", "for"]);
/** `for` inside `for`, at most this deep: each level repeats everything inside it. */
export const MAX_LOOP_DEPTH = 2;
const FOR_PATTERN = /^\s*([a-z_][A-Za-z0-9_]*)\s+in\s+([\s\S]+)$/;

export interface CompileOptions {
  name: string;
  section: SectionDefinition;
  /** What the template may read, when it is not a section's API data: a
   *  widget's model, worked out by code the compiler does not read. */
  scope?: Readonly<Record<string, Shape>>;
  /** Components it may place, such as a widget's charts, by element name. */
  elements?: Readonly<Record<string, WidgetElementDefinition>>;
}

export interface CompileResult {
  template: CompiledTemplate | null;
  errors: TemplateError[];
}

export function compileTemplate(source: string, options: CompileOptions): CompileResult {
  const errors: TemplateError[] = [];
  const report = (message: string, at: SourcePosition) => {
    errors.push(new TemplateError(message, at));
  };

  let nodes: TemplateNode[];
  try {
    nodes = parseTemplate(source);
  } catch (error) {
    if (error instanceof TemplateError) return { template: null, errors: [error] };
    throw error;
  }

  const rootScope = new Map<string, Shape>(Object.entries(options.scope ?? {}));
  for (const [name, schema] of Object.entries(options.section.data)) {
    const shape = schemaShape(schema);
    if (shape === undefined) {
      report(`Section data ${name} names ${schema}, which the API does not have`, {
        line: 1,
        column: 1,
      });
    }
    rootScope.set(name, shape ?? "any");
  }

  const exprs: string[] = [];
  const display: number[] = [];
  const exprIndex = new Map<string, number>();
  const expression = (
    source: string,
    scope: ExpressionScope,
    at: SourcePosition
  ): { index: number; shape: Shape } => {
    const check = checkExpression(source, scope);
    for (const problem of check.problems) report(`${problem}: ${source}`, at);
    let index = exprIndex.get(source);
    if (index === undefined) {
      index = exprs.length;
      exprs.push(source);
      exprIndex.set(source, index);
      if (check.display) display.push(index);
    }
    return { index, shape: check.shape };
  };

  const partCounts = new Map<string, number>();

  const attributesOf = (
    element: TemplateElement,
    scope: ExpressionScope,
    allowed: (name: string) => boolean
  ) => {
    const attrs: Record<string, string> = {};
    const bind: Record<string, number> = {};
    for (const attribute of element.attributes) {
      if (DIRECTIVES.has(attribute.name)) continue;
      const bound = attribute.name.startsWith(":");
      const name = bound ? attribute.name.slice(1) : attribute.name;
      if (RESERVED_DATA.has(name)) {
        report(`${name} is Initiative's own and cannot be set`, attribute);
        continue;
      }
      if (!allowed(name)) {
        report(`<${element.name}> cannot have ${attribute.name}`, attribute);
        continue;
      }
      if (attribute.value === null) {
        report(`${attribute.name} needs a value`, attribute);
        continue;
      }
      if (bound) {
        bind[name] = expression(attribute.value, scope, attribute).index;
      } else if (BOUND_ONLY.has(name)) {
        report(`Use :${name}="{ '--name': value }" to pass values to CSS`, attribute);
      } else {
        attrs[name] = attribute.value;
      }
    }
    return { attrs, bind };
  };

  const elementAllows = (tag: string) => (name: string) =>
    GLOBAL_ATTRIBUTES.has(name) ||
    BOUND_ONLY.has(name) ||
    name.startsWith("aria-") ||
    name.startsWith("data-") ||
    (ELEMENT_ATTRIBUTES[tag]?.has(name) ?? false);

  const directive = (element: TemplateElement, name: string): TemplateAttribute | undefined =>
    element.attributes.find((attribute) => attribute.name === name);

  /**
   * Where an element sits: inside an `if` or `for` (so it may not be there), and
   * how many `for`s deep.
   */
  interface Placement {
    conditional: boolean;
    loops: number;
  }

  /** One element, without its `if` or `for`, which `children` has already taken. */
  const compileElement = (
    element: TemplateElement,
    scope: ExpressionScope,
    placement: Placement
  ): CompiledNode | null => {
    if (element.name === "part") {
      const nameAttribute = directive(element, "name");
      const name = nameAttribute?.value;
      if (!name) {
        report("<part> needs a name", element);
        return null;
      }
      const definition = options.section.parts[name];
      if (!definition) {
        report(`${options.name} has no part called ${name}`, element);
        return null;
      }
      if (element.children.length > 0) report("<part> holds nothing: close it with />", element);
      if (definition.required && placement.conditional) {
        report(`${name} is required, so it cannot sit inside if or for`, element);
      }
      partCounts.set(name, (partCounts.get(name) ?? 0) + 1);
      const { attrs, bind } = attributesOf(
        { ...element, attributes: element.attributes.filter((a) => a.name !== "name") },
        scope,
        (attribute) => attribute === "class"
      );
      return { t: "part", name, attrs, bind };
    }
    const component = options.elements?.[element.name];
    if (component) {
      if (element.children.length > 0) {
        report(`<${element.name}> holds nothing: close it with />`, element);
      }
      const { attrs, bind } = attributesOf(element, scope, (name) =>
        Object.hasOwn(component.props, name)
      );
      // Keyed by the names the component takes, so the renderer passes them on as they are.
      const rename = (from: Record<string, string | number>) =>
        Object.fromEntries(
          Object.entries(from).map(([name, value]) => [component.props[name] as string, value])
        );
      return {
        t: "component",
        name: element.name,
        attrs: rename(attrs) as Record<string, string>,
        bind: rename(bind) as Record<string, number>,
      };
    }
    if (!ELEMENTS.has(element.name)) {
      report(`<${element.name}> is not an element templates may use`, element);
      return null;
    }
    const { attrs, bind } = attributesOf(element, scope, elementAllows(element.name));
    return {
      t: "el",
      tag: element.name,
      attrs,
      bind,
      kids: children(element.children, scope, placement),
    };
  };

  /** A list of siblings, folding `if`/`else-if`/`else` runs into one choice. */
  const children = (
    list: TemplateNode[],
    scope: ExpressionScope,
    placement: Placement
  ): CompiledNode[] => {
    const compiled: CompiledNode[] = [];
    let chain: Extract<CompiledNode, { t: "if" }> | null = null;
    const branch = { ...placement, conditional: true };
    for (const [position, node] of list.entries()) {
      if (node.kind === "text") {
        // A space between an if and the else-if or else that continues it
        // belongs to neither branch. Anywhere else it is a space.
        const next = list[position + 1];
        const continues =
          next?.kind === "element" &&
          next.attributes.some((a) => a.name === "else-if" || a.name === "else");
        if (chain && continues && node.parts.length === 1 && node.parts[0] === " ") continue;
        chain = null;
        compiled.push({
          t: "text",
          parts: node.parts.map((part) =>
            typeof part === "string" ? part : expression(part.expression, scope, part).index
          ),
        });
        continue;
      }
      const ifAttribute = directive(node, "if");
      const elseIf = directive(node, "else-if");
      const elseAttribute = directive(node, "else");
      const forAttribute = directive(node, "for");
      const branching = [ifAttribute, elseIf, elseAttribute].filter(Boolean).length;
      if (branching > 1) {
        report("Use one of if, else-if and else on an element", node);
        continue;
      }
      if (forAttribute && branching) {
        report("for and if on one element are ambiguous: wrap one in the other", node);
        continue;
      }

      if (forAttribute) {
        chain = null;
        const match = FOR_PATTERN.exec(forAttribute.value ?? "");
        if (!match) {
          report('for reads "item in list"', forAttribute);
          continue;
        }
        const [, item, listSource] = match as unknown as [string, string, string];
        const list = expression(listSource.trim(), scope, forAttribute);
        if (placement.loops + 1 > MAX_LOOP_DEPTH) {
          report(`for nests at most ${MAX_LOOP_DEPTH} deep`, forAttribute);
          continue;
        }
        const inner = new Map(scope);
        inner.set(item, itemShape(list.shape));
        const body = compileElement(node, inner, { conditional: true, loops: placement.loops + 1 });
        if (body) compiled.push({ t: "for", item, list: list.index, node: body });
        continue;
      }

      if (elseIf || elseAttribute) {
        if (!chain) {
          report(`${elseIf ? "else-if" : "else"} must follow an if`, node);
          continue;
        }
        const when = elseIf ? expression(elseIf.value ?? "", scope, elseIf).index : null;
        const body = compileElement(node, scope, branch);
        if (body) chain.branches.push({ when, node: body });
        if (elseAttribute) chain = null;
        continue;
      }

      if (ifAttribute) {
        const when = expression(ifAttribute.value ?? "", scope, ifAttribute).index;
        const body = compileElement(node, scope, branch);
        chain = { t: "if", branches: [] };
        if (body) chain.branches.push({ when, node: body });
        compiled.push(chain);
        continue;
      }

      chain = null;
      const body = compileElement(node, scope, placement);
      if (body) compiled.push(body);
    }
    return compiled;
  };

  const root = children(nodes, rootScope, { conditional: false, loops: 0 });

  for (const [name, definition] of Object.entries(options.section.parts)) {
    const count = partCounts.get(name) ?? 0;
    if (definition.required && count !== 1) {
      report(
        count === 0
          ? `${options.name} must place its ${name} part`
          : `${name} is placed ${count} times; a required part appears once`,
        { line: 1, column: 1 }
      );
    }
  }

  if (errors.length > 0) return { template: null, errors };
  return { template: { section: options.name, exprs, display, root }, errors };
}
