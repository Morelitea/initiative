/**
 * Remark plugins for rendering comment bodies.
 *
 * Comments are markdown, but they also carry the mention syntax the composer
 * writes — `@[Name](12)`, `#task[Title](3)`, `#doc[…](3)`, `#project[…](3)`.
 * That syntax is shaped like a markdown link, so remark parses it before any
 * text-level pass can see it: the result is a text node ending in the trigger
 * followed by a link whose url is the entity id. `remarkMentions` recognises
 * that pair and folds it back into a single mention node.
 *
 * Working after the parse (rather than pre-processing the raw string) means a
 * mention written inside code stays literal, because remark never turned it
 * into a link there.
 */

/** Minimal structural view of the mdast nodes these plugins touch. */
interface MdastNode {
  type: string;
  value?: string;
  url?: string;
  alt?: string;
  children?: MdastNode[];
  data?: Record<string, unknown>;
}

export type MentionType = "user" | "task" | "doc" | "project";

/** Trigger text preceding the link, longest first so `#doc` can't shadow a
 *  longer trigger that happens to share its prefix. */
const TRIGGERS: { trigger: string; type: MentionType }[] = [
  { trigger: "#project", type: "project" },
  { trigger: "#task", type: "task" },
  { trigger: "#doc", type: "doc" },
  { trigger: "@", type: "user" },
];

const ENTITY_ID = /^\d+$/;

/** Collect the plain text of a node subtree — a mention's label renders as a
 *  badge or link, so any inline formatting inside it is dropped. */
function textOf(node: MdastNode): string {
  if (typeof node.value === "string") return node.value;
  return (node.children ?? []).map(textOf).join("");
}

/** A trigger only counts at a word boundary, so `email@[x](1)` stays a link. */
function triggerAt(text: string): { trigger: string; type: MentionType } | null {
  for (const candidate of TRIGGERS) {
    if (!text.endsWith(candidate.trigger)) continue;
    const before = text[text.length - candidate.trigger.length - 1];
    if (before === undefined || /[\s([{]/.test(before)) return candidate;
  }
  return null;
}

function mentionNode(type: MentionType, id: string, label: string): MdastNode {
  return {
    type: "mention",
    data: {
      hName: "span",
      hProperties: {
        "data-mention-type": type,
        "data-mention-id": id,
        "data-mention-label": label,
      },
    },
    children: [{ type: "text", value: label }],
  };
}

function visitParents(node: MdastNode, fn: (parent: MdastNode) => void) {
  if (!node.children) return;
  fn(node);
  for (const child of node.children) visitParents(child, fn);
}

/** Fold `text-ending-in-trigger` + `link` pairs back into mention nodes. */
export function remarkMentions() {
  return (tree: MdastNode) => {
    visitParents(tree, (parent) => {
      const children = parent.children;
      if (!children) return;

      for (let i = children.length - 1; i >= 0; i--) {
        const link = children[i];
        if (link.type !== "link" || !link.url || !ENTITY_ID.test(link.url)) continue;

        const previous = children[i - 1];
        if (previous?.type !== "text" || typeof previous.value !== "string") continue;

        const match = triggerAt(previous.value);
        if (!match) continue;

        const label = textOf(link);
        if (!label) continue;

        previous.value = previous.value.slice(0, -match.trigger.length);
        children[i] = mentionNode(match.type, link.url, label);
        if (!previous.value) children.splice(i - 1, 1);
      }
    });
  };
}

/**
 * Turn an image into a link to itself, named by its alt text, so a comment
 * reports what it points at rather than fetching it. An image the author
 * already wrapped in a link contributes only its name: the wrapping link keeps
 * its own destination, and a link cannot legally hold another.
 */
export function remarkImageLinks() {
  return (tree: MdastNode) => {
    visitParents(tree, (parent) => {
      const children = parent.children;
      if (!children) return;

      for (let i = children.length - 1; i >= 0; i--) {
        const image = children[i];
        if (image.type !== "image") continue;

        const label = textOf(image) || image.alt || image.url || "";
        if (!label) {
          children.splice(i, 1);
          continue;
        }

        if (parent.type === "link" || !image.url) {
          children[i] = { type: "text", value: label };
          continue;
        }

        children[i] = {
          type: "link",
          url: image.url,
          children: [{ type: "text", value: label }],
        };
      }
    });
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
