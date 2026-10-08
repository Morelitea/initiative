/**
 * Read a template's text into a tree.
 *
 * A template is HTML written to be a tree: every element is closed, by its end
 * tag or by `/>`, and attribute values are quoted. That is all a template needs,
 * so this reads that and refuses the rest with the line and column, rather than
 * guessing at broken markup the way a browser has to. What is allowed where is
 * the compiler's business (compile.ts); this only knows the syntax.
 *
 * Kept free of the browser and of `@/` imports: the Vite plugin runs it in Node.
 */

export interface SourcePosition {
  line: number;
  column: number;
}

export interface TemplateAttribute extends SourcePosition {
  name: string;
  /** Null for a bare attribute such as `else`. */
  value: string | null;
}

export interface TemplateElement extends SourcePosition {
  kind: "element";
  name: string;
  attributes: TemplateAttribute[];
  children: TemplateNode[];
}

export interface TemplateExpression extends SourcePosition {
  expression: string;
}

export interface TemplateText extends SourcePosition {
  kind: "text";
  /** Literal text and `{{ expression }}` parts, in order. */
  parts: Array<string | TemplateExpression>;
}

export type TemplateNode = TemplateElement | TemplateText;

export class TemplateError extends Error {
  readonly line: number;
  readonly column: number;

  constructor(message: string, position: SourcePosition) {
    super(`${message} (line ${position.line}, column ${position.column})`);
    this.name = "TemplateError";
    this.line = position.line;
    this.column = position.column;
  }
}

/** Elements HTML closes on its own; `<hr>` and `<hr />` both stand alone. */
const VOID_ELEMENTS = new Set(["br", "hr", "img"]);

const ENTITIES: Record<string, string> = {
  amp: "&",
  lt: "<",
  gt: ">",
  quot: '"',
  apos: "'",
  nbsp: " ",
};

const NAME = /[a-z][a-z0-9-]*/y;
const ATTRIBUTE_NAME = /[:a-z][a-z0-9:_.-]*/y;
const SPACE = /\s*/y;

export function parseTemplate(source: string): TemplateNode[] {
  let index = 0;

  const lineStarts = [0];
  for (let i = 0; i < source.length; i++) if (source[i] === "\n") lineStarts.push(i + 1);
  const positionAt = (offset: number): SourcePosition => {
    let low = 0;
    let high = lineStarts.length - 1;
    while (low < high) {
      const middle = (low + high + 1) >> 1;
      if ((lineStarts[middle] as number) <= offset) low = middle;
      else high = middle - 1;
    }
    return { line: low + 1, column: offset - (lineStarts[low] as number) + 1 };
  };
  const fail = (message: string, offset = index): never => {
    throw new TemplateError(message, positionAt(offset));
  };

  const match = (pattern: RegExp): string | null => {
    pattern.lastIndex = index;
    const found = pattern.exec(source);
    if (!found) return null;
    index += found[0].length;
    return found[0];
  };
  const skipSpace = () => match(SPACE);

  const decode = (text: string, offset: number): string =>
    text.replace(/&(#x[0-9a-f]+|#[0-9]+|[a-z]+);/gi, (entity, body: string) => {
      if (body[0] === "#") {
        const code =
          body[1] === "x" || body[1] === "X"
            ? Number.parseInt(body.slice(2), 16)
            : Number.parseInt(body.slice(1), 10);
        if (!(code > 0 && code <= 0x10ffff)) fail(`${entity} is not a character`, offset);
        return String.fromCodePoint(code);
      }
      const known = ENTITIES[body.toLowerCase()];
      if (known === undefined) fail(`Unknown entity ${entity}`, offset);
      return known as string;
    });

  /**
   * Where the `}}` that closes the expression opened at `start` begins: the
   * first one outside a string and outside any braces the expression opens, so
   * `{{ '}}' }}` and `{{ {'a': {'b': 1}} }}` are read whole.
   */
  const closingBraces = (start: number): number => {
    let depth = 0;
    let quote = "";
    for (let i = start; i < source.length; i++) {
      const char = source[i] as string;
      if (quote) {
        if (char === "\\" && quote.length === 1) i++;
        else if (source.startsWith(quote, i)) {
          i += quote.length - 1;
          quote = "";
        }
        continue;
      }
      if (char === "'" || char === '"') {
        quote = source.startsWith(char.repeat(3), i) ? char.repeat(3) : char;
        i += quote.length - 1;
      } else if (char === "{") depth++;
      else if (char === "}") {
        if (depth > 0) depth--;
        else if (source[i + 1] === "}") return i;
      }
    }
    return -1;
  };

  const readText = (): TemplateText | null => {
    const start = index;
    const parts: TemplateText["parts"] = [];
    let literal = "";
    let literalStart = index;
    const flush = () => {
      if (literal) parts.push(decode(literal, literalStart));
      literal = "";
    };
    while (index < source.length && source[index] !== "<") {
      if (source.startsWith("{{", index)) {
        flush();
        const open = index;
        const close = closingBraces(index + 2);
        if (close === -1) fail("Unclosed {{", open);
        const expression = source.slice(index + 2, close).trim();
        if (!expression) fail("Empty {{ }}", open);
        parts.push({ expression, ...positionAt(open + 2) });
        index = close + 2;
        literalStart = index;
        continue;
      }
      if (source.startsWith("}}", index)) fail("}} without {{");
      literal += source[index];
      index++;
    }
    flush();
    // Whitespace that breaks a line is the file's layout, so it goes. Whitespace
    // within a line is the page's, so it stays as one space: the one between
    // `<span>Due</span> <strong>today</strong>`. A no-break space is text.
    const meaningful = parts.some((part) => typeof part !== "string" || /[^ \t\r\n]/.test(part));
    if (!meaningful) {
      const raw = source.slice(start, index);
      return raw.includes("\n") ? null : { kind: "text", parts: [" "], ...positionAt(start) };
    }
    const collapsed = parts.map((part) =>
      typeof part === "string" ? part.replace(/[ \t\r\n]+/g, " ") : part
    );
    return { kind: "text", parts: collapsed, ...positionAt(start) };
  };

  const readAttributes = (): TemplateAttribute[] => {
    const attributes: TemplateAttribute[] = [];
    const seen = new Set<string>();
    for (;;) {
      skipSpace();
      if (source[index] === ">" || source.startsWith("/>", index)) return attributes;
      const start = index;
      const name = match(ATTRIBUTE_NAME);
      if (!name) fail("Expected an attribute name, or > to end the tag");
      if (seen.has(name as string)) fail(`Attribute ${name} is given twice`, start);
      seen.add(name as string);
      let value: string | null = null;
      skipSpace();
      if (source[index] === "=") {
        index++;
        skipSpace();
        const quote = source[index];
        if (quote !== '"' && quote !== "'") fail("Attribute values must be quoted");
        const end = source.indexOf(quote as string, index + 1);
        if (end === -1) fail("Unclosed attribute value");
        value = decode(source.slice(index + 1, end), index + 1);
        index = end + 1;
      }
      attributes.push({ name: name as string, value, ...positionAt(start) });
    }
  };

  const readChildren = (closing: string | null): TemplateNode[] => {
    const children: TemplateNode[] = [];
    for (;;) {
      if (index >= source.length) {
        if (closing) fail(`<${closing}> is never closed`);
        return children;
      }
      if (source.startsWith("<!--", index)) {
        const end = source.indexOf("-->", index + 4);
        if (end === -1) fail("Unclosed comment");
        index = end + 3;
        continue;
      }
      if (source.startsWith("</", index)) {
        const start = index;
        index += 2;
        const name = match(NAME);
        skipSpace();
        if (source[index] !== ">") fail("Expected > to end the closing tag");
        index++;
        if (name !== closing) {
          fail(
            closing ? `</${name}> closes <${closing}>` : `</${name}> has nothing to close`,
            start
          );
        }
        return children;
      }
      if (source[index] === "<") {
        children.push(readElement());
        continue;
      }
      const text = readText();
      if (text) children.push(text);
    }
  };

  const readElement = (): TemplateElement => {
    const start = index;
    index++;
    const name = match(NAME);
    if (!name) fail("Expected an element name after <");
    const attributes = readAttributes();
    const element: TemplateElement = {
      kind: "element",
      name: name as string,
      attributes,
      children: [],
      ...positionAt(start),
    };
    if (source.startsWith("/>", index)) {
      index += 2;
      return element;
    }
    index++;
    if (!VOID_ELEMENTS.has(element.name)) element.children = readChildren(element.name);
    return element;
  };

  return readChildren(null);
}
