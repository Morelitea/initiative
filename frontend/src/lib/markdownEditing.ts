/**
 * The text edits a markdown toolbar makes.
 *
 * Every one of these is a pure function from "what is in the field and what is
 * selected" to the same, so the button that bolds a word can be read and
 * tested without a browser. The component layer does nothing but read the
 * selection off the textarea, apply one of these, and put the selection back.
 *
 * Each edit toggles: pressing bold on a bold word unbolds it, and pressing
 * quote on a quoted block unquotes it. That is what makes a toolbar feel like
 * a toolbar rather than a stamp.
 */

/** A field's contents and what is selected in it. */
export interface MarkdownSelection {
  value: string;
  start: number;
  end: number;
}

export type MarkdownTransform = (state: MarkdownSelection) => MarkdownSelection;

/** Start of the line `index` sits on. */
const lineStart = (value: string, index: number) => value.lastIndexOf("\n", index - 1) + 1;

/** End of the line `index` sits on, excluding the newline itself. */
const lineEnd = (value: string, index: number) => {
  const next = value.indexOf("\n", index);
  return next === -1 ? value.length : next;
};

/**
 * Replace the whole block of lines the selection spans.
 *
 * A selection stays a selection, over the rewritten block. A caret stays a
 * caret: it keeps its distance from the end of the block, which is what puts
 * it after a list marker that was just added rather than in front of one — and
 * means the next thing typed continues the line instead of replacing it.
 */
const replaceBlock = (
  { value, start, end }: MarkdownSelection,
  rewrite: (block: string) => string
): MarkdownSelection => {
  const from = lineStart(value, start);
  const to = lineEnd(value, end);
  const next = rewrite(value.slice(from, to));
  const result = value.slice(0, from) + next + value.slice(to);

  if (start === end) {
    const caret = Math.max(from, from + next.length - (to - start));
    return { value: result, start: caret, end: caret };
  }
  return { value: result, start: from, end: from + next.length };
};

/**
 * Wrap the selection in a marker, or unwrap it if it is already wrapped —
 * whether the markers sit inside the selection (`**word**` selected whole) or
 * just outside it (`word` selected inside an already-bold run).
 *
 * With nothing selected the markers go in empty and the caret lands between
 * them, so the next thing typed is inside.
 */
export const toggleWrap =
  (marker: string): MarkdownTransform =>
  ({ value, start, end }) => {
    const selected = value.slice(start, end);
    const before = value.slice(0, start);
    const after = value.slice(end);

    if (before.endsWith(marker) && after.startsWith(marker)) {
      return {
        value: before.slice(0, -marker.length) + selected + after.slice(marker.length),
        start: start - marker.length,
        end: end - marker.length,
      };
    }

    if (
      selected.length >= marker.length * 2 &&
      selected.startsWith(marker) &&
      selected.endsWith(marker)
    ) {
      const inner = selected.slice(marker.length, -marker.length);
      return { value: before + inner + after, start, end: start + inner.length };
    }

    return {
      value: before + marker + selected + marker + after,
      start: start + marker.length,
      end: end + marker.length,
    };
  };

const FENCE = "```";

/** Fence the selected lines, or unfence them if they already are. */
const toggleFence: MarkdownTransform = (state) =>
  replaceBlock(state, (block) => {
    const lines = block.split("\n");
    if (lines.length >= 2 && lines[0].startsWith(FENCE) && lines[lines.length - 1] === FENCE) {
      return lines.slice(1, -1).join("\n");
    }
    return `${FENCE}\n${block}\n${FENCE}`;
  });

/**
 * Code, at the size of what is selected: a run within a line becomes inline
 * code, and a selection spanning lines becomes a fenced block.
 */
export const toggleCode: MarkdownTransform = (state) =>
  state.value.slice(state.start, state.end).includes("\n")
    ? toggleFence(state)
    : toggleWrap("`")(state);

/** How a line-prefixed block (a list, a quote) is written and recognised. */
export interface LinePrefixSpec {
  /** The prefix for the nth prefixed line — ordered lists count, others don't. */
  prefix: (index: number) => string;
  /** Matches this kind of prefix at the start of a line, for removing it. */
  match: RegExp;
  /** Matches a line that already IS this kind, when that is narrower than what
   *  the prefix strips — a checklist item is not a plain bullet. */
  test?: RegExp;
}

export const QUOTE: LinePrefixSpec = { prefix: () => "> ", match: /^ *> ?/ };
export const BULLET_LIST: LinePrefixSpec = {
  prefix: () => "- ",
  match: /^ *[-*+] /,
  test: /^ *[-*+] (?!\[[ xX]\] )/,
};
export const NUMBERED_LIST: LinePrefixSpec = {
  prefix: (index) => `${index + 1}. `,
  match: /^ *\d+\. /,
};
export const TASK_LIST: LinePrefixSpec = {
  prefix: () => "- [ ] ",
  match: /^ *[-*+] \[[ xX]\] /,
};

/** Every list shape, most specific first, so re-prefixing a line replaces the
 *  list it was in rather than nesting inside it. */
const LIST_SPECS = [TASK_LIST, BULLET_LIST, NUMBERED_LIST];

/**
 * Put a prefix on every selected line, or take it off every line that has it.
 *
 * Switching between list kinds swaps the prefix: a checklist asked to become
 * bullets loses its boxes instead of growing a second marker.
 */
export const toggleLinePrefix = (spec: LinePrefixSpec): MarkdownTransform => {
  const isPrefixed = (line: string) => (spec.test ?? spec.match).test(line);
  const strip = (line: string) =>
    LIST_SPECS.includes(spec)
      ? LIST_SPECS.reduce((text, other) => text.replace(other.match, ""), line)
      : line.replace(spec.match, "");

  return (state) =>
    replaceBlock(state, (block) => {
      const lines = block.split("\n");
      const written = lines.filter((line) => line.trim().length > 0);
      const allPrefixed = written.length > 0 && written.every(isPrefixed);

      if (allPrefixed) {
        return lines.map((line) => line.replace(spec.match, "")).join("\n");
      }

      let index = 0;
      return lines
        .map((line) => {
          // A blank line inside a multi-line selection separates blocks; only a
          // selection that is nothing but a blank line gets a prefix, so the
          // button can start a list in an empty field.
          if (line.trim().length === 0 && lines.length > 1) return line;
          const prefix = spec.prefix(index);
          index += 1;
          return prefix + strip(line);
        })
        .join("\n");
    });
};

/** The deepest heading the button cycles to before clearing. */
const MAX_HEADING = 3;

/**
 * Cycle the selected lines through heading levels and back to plain text, the
 * way one heading button has to serve six levels.
 */
export const cycleHeading: MarkdownTransform = (state) =>
  replaceBlock(state, (block) => {
    const lines = block.split("\n");
    const current = /^(#{1,6}) /.exec(lines[0])?.[1].length ?? 0;
    const next = current >= MAX_HEADING ? 0 : current + 1;
    return lines
      .map((line) => {
        const bare = line.replace(/^#{1,6} +/, "");
        return next === 0 ? bare : `${"#".repeat(next)} ${bare}`;
      })
      .join("\n");
  });

/** Text that is already an address, so the link should be built around it. */
const URL_PATTERN = /^(https?:\/\/|mailto:)\S+$/i;

/** The word that stands in for an address until one is typed over it. */
export const LINK_PLACEHOLDER = "url";

/**
 * Build a link around the selection — a selected address becomes the target
 * and the caret lands where the words go; anything else becomes the words and
 * the placeholder address is selected, ready to be pasted over.
 */
export const insertLink: MarkdownTransform = ({ value, start, end }) => {
  const selected = value.slice(start, end);
  const before = value.slice(0, start);
  const after = value.slice(end);

  if (URL_PATTERN.test(selected)) {
    return {
      value: `${before}[](${selected})${after}`,
      start: start + 1,
      end: start + 1,
    };
  }

  const inserted = `[${selected}](${LINK_PLACEHOLDER})`;
  if (selected.length === 0) {
    return { value: before + inserted + after, start: start + 1, end: start + 1 };
  }
  const urlAt = start + selected.length + 3;
  return {
    value: before + inserted + after,
    start: urlAt,
    end: urlAt + LINK_PLACEHOLDER.length,
  };
};

/** A line that carries a list marker or a quote: indent, marker, rest. */
const CONTINUABLE_LINE = /^(\s*)([-*+] \[[ xX]\] |[-*+] |\d+\. |> )(.*)$/;

/**
 * What Enter does on a list or quote line: carry the marker down to the next
 * one, so a list is typed rather than assembled.
 *
 * Enter on an item with nothing in it means the opposite — the writer is done
 * with the list — so it takes the marker off instead of laying another one
 * down. A number goes up by one; a ticked box comes down unticked.
 *
 * `null` means this line is not one of those and Enter should do what Enter
 * normally does.
 */
export const continueList = ({
  value,
  start,
  end,
}: MarkdownSelection): MarkdownSelection | null => {
  if (start !== end) return null;

  const from = lineStart(value, start);
  const match = CONTINUABLE_LINE.exec(value.slice(from, lineEnd(value, start)));
  if (!match) return null;

  const [, indent, marker, content] = match;
  const afterMarker = from + indent.length + marker.length;
  // Before the marker, Enter is just Enter: there is no item to continue yet.
  if (start < afterMarker) return null;

  if (content.trim() === "") {
    return {
      value: value.slice(0, from) + value.slice(afterMarker),
      start: from,
      end: from,
    };
  }

  const next = /^\d+\. $/.test(marker)
    ? `${Number.parseInt(marker, 10) + 1}. `
    : marker.replace(/\[[xX]\]/, "[ ]");
  const inserted = `\n${indent}${next}`;
  const caret = start + inserted.length;
  return {
    value: value.slice(0, start) + inserted + value.slice(start),
    start: caret,
    end: caret,
  };
};
