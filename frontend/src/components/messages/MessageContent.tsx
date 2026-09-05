import type { ComponentPropsWithoutRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { remarkImageLinks, remarkLineBreaks } from "@/lib/remarkProse";
import { cn } from "@/lib/utils";

/**
 * One message's words, as markdown.
 *
 * The same basic formatting a comment gets — emphasis, code, lists, quotes,
 * links — and deliberately less besides. Two things are left out:
 *
 * * **Mentions.** They are read back against a community's roster, and a
 *   direct message belongs to no community. There is nothing here to resolve
 *   them against and nobody who should be asked to.
 * * **Pictures.** An image becomes a link carrying its name, so the page loads
 *   nothing of its own and the reader decides whether to follow it.
 *
 * Markdown is rendered without raw HTML, and links keep only the schemes
 * react-markdown will follow.
 */
const PROSE =
  "wrap-break-word [&_a:hover]:underline [&_a]:break-all [&_a]:underline [&_blockquote]:border-current/30 [&_blockquote]:border-l-2 [&_blockquote]:pl-2 [&_code]:rounded [&_code]:bg-black/15 [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-xs [&_h1]:font-semibold [&_h1]:text-base [&_h2]:font-semibold [&_h2]:text-base [&_h3]:font-semibold [&_h3]:text-sm [&_h4]:font-semibold [&_h5]:font-semibold [&_h6]:font-semibold [&_hr]:border-current/30 [&_li]:mt-0.5 [&_ol]:list-decimal [&_ol]:pl-5 [&_pre]:overflow-x-auto [&_pre]:rounded [&_pre]:bg-black/15 [&_pre]:p-2 [&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_strong]:font-semibold [&_table]:block [&_table]:w-fit [&_table]:overflow-x-auto [&_td]:border [&_td]:border-current/30 [&_td]:px-2 [&_td]:py-1 [&_th]:border [&_th]:border-current/30 [&_th]:px-2 [&_th]:py-1 [&_th]:font-semibold [&_ul]:list-disc [&_ul]:pl-5 [&>*+*]:mt-2";

type AnchorProps = ComponentPropsWithoutRef<"a"> & { node?: unknown };
type ImageProps = ComponentPropsWithoutRef<"img"> & { node?: unknown };

const MessageAnchor = ({ children, node: _node, ...props }: AnchorProps) => (
  <a {...props} target="_blank" rel="noopener noreferrer">
    {children}
  </a>
);

/** `remarkImageLinks` rewrites every image ahead of this, so reaching here
 *  means an unexpected shape — name it rather than fetch it. */
const MessageImage = ({ src, alt }: ImageProps) => (
  <span>{alt || (typeof src === "string" ? src : "")}</span>
);

const COMPONENTS = { a: MessageAnchor, img: MessageImage };
const PLUGINS = [remarkGfm, remarkImageLinks, remarkLineBreaks];

export const MessageContent = ({ body, className }: { body: string; className?: string }) => (
  <div className={cn(PROSE, className)}>
    <ReactMarkdown remarkPlugins={PLUGINS} components={COMPONENTS}>
      {body}
    </ReactMarkdown>
  </div>
);
