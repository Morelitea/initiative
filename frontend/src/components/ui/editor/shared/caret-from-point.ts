export function caretFromPoint(
  x: number,
  y: number
): null | {
  offset: number;
  node: Node;
} {
  if (typeof document.caretRangeFromPoint !== "undefined") {
    const range = document.caretRangeFromPoint(x, y);
    if (range === null) {
      return null;
    }
    return {
      node: range.startContainer,
      offset: range.startOffset,
    };
    // @ts-expect-error - Firefox API not in standard types
  } else if (document.caretPositionFromPoint !== "undefined") {
    const range = document.caretPositionFromPoint(x, y);
    if (range === null) {
      return null;
    }
    return {
      node: range.offsetNode,
      offset: range.offset,
    };
  } else {
    // Gracefully handle IE
    return null;
  }
}
