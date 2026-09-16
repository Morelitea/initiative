import { describe, expect, it } from "vitest";

import {
  BULLET_LIST,
  continueList,
  cycleHeading,
  insertLink,
  type MarkdownSelection,
  type MarkdownTransform,
  NUMBERED_LIST,
  QUOTE,
  TASK_LIST,
  toggleCode,
  toggleLinePrefix,
  toggleWrap,
} from "./markdownEditing";

/**
 * A field written as a string with the selection marked by `|`, so a case
 * reads as what the writer sees rather than as a pair of offsets. One `|` is a
 * caret; two mark the ends of a selection.
 */
const parse = (marked: string): MarkdownSelection => {
  const start = marked.indexOf("|");
  const end = marked.indexOf("|", start + 1);
  const value = marked.replaceAll("|", "");
  return { value, start, end: end === -1 ? start : end - 1 };
};

const render = ({ value, start, end }: MarkdownSelection) =>
  start === end
    ? `${value.slice(0, start)}|${value.slice(start)}`
    : `${value.slice(0, start)}|${value.slice(start, end)}|${value.slice(end)}`;

const run = (transform: MarkdownTransform, marked: string) => render(transform(parse(marked)));

const bold = toggleWrap("**");

describe("toggleWrap", () => {
  it("wraps the selection and keeps it selected", () => {
    expect(run(bold, "hello |world|")).toBe("hello **|world|**");
  });

  it("opens empty markers with the caret between them", () => {
    expect(run(bold, "hello |")).toBe("hello **|**");
  });

  it("unwraps when the markers are inside the selection", () => {
    expect(run(bold, "hello |**world**|")).toBe("hello |world|");
  });

  it("unwraps when the markers sit just outside the selection", () => {
    expect(run(bold, "hello **|world|**")).toBe("hello |world|");
  });

  it("does not mistake the marker itself for a wrapped run", () => {
    expect(run(bold, "|**|")).toBe("**|**|**");
  });
});

describe("toggleCode", () => {
  it("uses inline code within a line", () => {
    expect(run(toggleCode, "call |render()| twice")).toBe("call `|render()|` twice");
  });

  it("fences a selection that spans lines", () => {
    expect(run(toggleCode, "|one\ntwo|")).toBe("|```\none\ntwo\n```|");
  });

  it("unfences a block that is already fenced", () => {
    expect(run(toggleCode, "|```\none\ntwo\n```|")).toBe("|one\ntwo|");
  });
});

describe("toggleLinePrefix", () => {
  const bullets = toggleLinePrefix(BULLET_LIST);
  const numbers = toggleLinePrefix(NUMBERED_LIST);
  const tasks = toggleLinePrefix(TASK_LIST);
  const quote = toggleLinePrefix(QUOTE);

  it("prefixes every line the selection touches", () => {
    expect(run(bullets, "on|e\ntw|o")).toBe("|- one\n- two|");
  });

  it("numbers an ordered list from one", () => {
    expect(run(numbers, "|one\ntwo\nthree|")).toBe("|1. one\n2. two\n3. three|");
  });

  it("removes the prefix when every line already has it", () => {
    expect(run(bullets, "|- one\n- two|")).toBe("|one\ntwo|");
  });

  it("starts a list from an empty field, with the caret after the marker", () => {
    expect(run(bullets, "|")).toBe("- |");
  });

  it("leaves a caret where it was on the line, so typing continues it", () => {
    expect(run(bullets, "on|e")).toBe("- on|e");
  });

  it("swaps one list kind for another rather than nesting them", () => {
    expect(run(bullets, "|- [ ] one|")).toBe("|- one|");
    expect(run(tasks, "|- one|")).toBe("|- [ ] one|");
  });

  it("treats a checklist as a checklist, not as bullets to remove", () => {
    expect(run(tasks, "|- [ ] one\n- [x] two|")).toBe("|one\ntwo|");
  });

  it("leaves blank lines inside a selection alone", () => {
    expect(run(quote, "|one\n\ntwo|")).toBe("|> one\n\n> two|");
  });

  it("does not reach the line after a selection that ends on a newline", () => {
    // Selecting a whole line takes its newline with it, and that offset is the
    // start of the next line — which the writer did not select.
    expect(run(bullets, "|one\n|two")).toBe("|- one|\ntwo");
  });

  it("only takes the prefix off when every written line has it", () => {
    expect(run(bullets, "|- one\ntwo|")).toBe("|- one\n- two|");
  });
});

describe("cycleHeading", () => {
  it("cycles a line through the levels and back to plain text", () => {
    expect(run(cycleHeading, "ti|tle")).toBe("# ti|tle");
    expect(run(cycleHeading, "|# title|")).toBe("|## title|");
    expect(run(cycleHeading, "|## title|")).toBe("|### title|");
    expect(run(cycleHeading, "|### title|")).toBe("|title|");
  });

  it("keeps a selection a selection", () => {
    expect(run(cycleHeading, "|title|")).toBe("|# title|");
  });

  it("takes its level from the first selected line", () => {
    expect(run(cycleHeading, "|# one\ntwo|")).toBe("|## one\n## two|");
  });
});

describe("insertLink", () => {
  it("makes the selection the words and selects the placeholder address", () => {
    expect(run(insertLink, "see |the docs|")).toBe("see [the docs](|url|)");
  });

  it("makes a selected address the target and puts the caret in the words", () => {
    expect(run(insertLink, "|https://example.com|")).toBe("[|](https://example.com)");
  });

  it("puts the caret in the words when nothing is selected", () => {
    expect(run(insertLink, "see |")).toBe("see [|](url)");
  });
});

describe("continueList", () => {
  const carry = (marked: string) => {
    const next = continueList(parse(marked));
    return next === null ? null : render(next);
  };

  it("carries a bullet down to the next line", () => {
    expect(carry("- one|")).toBe("- one\n- |");
  });

  it("counts an ordered list on", () => {
    expect(carry("1. one\n2. two|")).toBe("1. one\n2. two\n3. |");
  });

  it("carries a checklist down unticked", () => {
    expect(carry("- [x] one|")).toBe("- [x] one\n- [ ] |");
  });

  it("keeps the indent of the item it is continuing", () => {
    expect(carry("  - one|")).toBe("  - one\n  - |");
  });

  it("ends the list when the item is empty", () => {
    expect(carry("- one\n- |")).toBe("- one\n|");
  });

  it("takes the rest of the line with it when the caret is mid-item", () => {
    expect(carry("- one| two")).toBe("- one\n- | two");
  });

  it("leaves an ordinary line to Enter", () => {
    expect(carry("just a sentence|")).toBe(null);
  });

  it("leaves a caret in front of the marker to Enter", () => {
    expect(carry("|- one")).toBe(null);
  });

  it("leaves a selection to Enter, which replaces it", () => {
    expect(carry("- |one|")).toBe(null);
  });
});
