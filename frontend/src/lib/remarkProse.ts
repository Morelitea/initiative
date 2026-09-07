/**
 * The markdown passes every body in the product goes through.
 *
 * Nothing here is about comments or about messages: one turns an image into a
 * name rather than a fetch, the other treats a newline as a newline. Both are
 * wanted wherever somebody types prose into a box, so they live below the
 * surfaces that use them rather than in one of them.
 */

/** Minimal structural view of the mdast nodes these plugins touch. */
export interface MdastNode {
  type: string;
  value?: string;
  url?: string;
  alt?: string;
  identifier?: string;
  children?: MdastNode[];
  data?: Record<string, unknown>;
}

/** Both spellings of an image and of a link — inline, and by reference. */
export const IMAGE_TYPES = new Set(["image", "imageReference"]);
export const LINK_TYPES = new Set(["link", "linkReference"]);

/** Walk every node that has children, parents before their children. */
export function visitParents(node: MdastNode, fn: (parent: MdastNode) => void) {
  if (!node.children) return;
  fn(node);
  for (const child of node.children) visitParents(child, fn);
}

/**
 * Turn an image into a link to itself, named by its alt text, so a comment
 * reports what it points at rather than fetching it. An image the author
 * already wrapped in a link contributes only its name: the wrapping link keeps
 * its own destination, and a link cannot legally hold another.
 */
export function remarkImageLinks() {
  return (tree: MdastNode) => {
    // A reference-style image names a definition elsewhere in the document
    // rather than carrying its own address.
    const definitions = new Map<string, string>();
    visitParents(tree, (parent) => {
      for (const child of parent.children ?? []) {
        if (child.type === "definition" && child.identifier && child.url) {
          definitions.set(child.identifier, child.url);
        }
      }
    });

    const urlOf = (node: MdastNode) =>
      node.url ?? (node.identifier ? definitions.get(node.identifier) : undefined);

    // The wrapping link can be any number of levels up — emphasis, a heading,
    // a table cell — so this tracks the ancestry rather than the parent alone.
    const rewrite = (node: MdastNode, insideLink: boolean) => {
      const children = node.children;
      if (!children) return;

      for (let i = children.length - 1; i >= 0; i--) {
        const child = children[i];
        if (!IMAGE_TYPES.has(child.type)) {
          rewrite(child, insideLink || LINK_TYPES.has(child.type));
          continue;
        }

        const url = urlOf(child);
        const label = child.alt || url || "";
        if (!label) {
          children.splice(i, 1);
          continue;
        }

        children[i] =
          insideLink || !url
            ? { type: "text", value: label }
            : { type: "link", url, children: [{ type: "text", value: label }] };
      }
    };

    rewrite(tree, LINK_TYPES.has(tree.type));
  };
}

/**
 * Treat a single newline as a line break, the way comment authors expect from
 * a plain textarea — markdown would otherwise join those lines into one
 * paragraph.
 */
export function remarkLineBreaks() {
  return (tree: MdastNode) => {
    visitParents(tree, (parent) => {
      const children = parent.children;
      if (!children) return;

      for (let i = children.length - 1; i >= 0; i--) {
        const child = children[i];
        if (child.type !== "text" || typeof child.value !== "string") continue;
        if (!child.value.includes("\n")) continue;

        const replacement: MdastNode[] = [];
        // A trailing space before the newline is markdown's own hard break;
        // trimming it keeps the rendered gap consistent either way.
        const segments = child.value.split("\n");
        segments.forEach((segment, index) => {
          if (index > 0) replacement.push({ type: "break" });
          const value = index < segments.length - 1 ? segment.replace(/[ \t]+$/, "") : segment;
          if (value) replacement.push({ type: "text", value });
        });

        children.splice(i, 1, ...replacement);
      }
    });
  };
}
