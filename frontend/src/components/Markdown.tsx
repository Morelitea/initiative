import type { ComponentPropsWithoutRef, MouseEvent } from "react";
import ReactMarkdown from "react-markdown";
import rehypeSlug from "rehype-slug";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils";

interface MarkdownProps {
  content: string;
  className?: string;
}

/** Anything that can be wider than its container is wrapped or scrolled here,
 *  so rendered markdown never stretches the card or panel it sits in. */
const CONTAINMENT_CLASS =
  "wrap-break-word [&_a]:break-all [&_code]:wrap-break-word [&_img]:h-auto [&_img]:max-w-full [&_pre]:max-w-full [&_pre]:overflow-x-auto [&_pre]:whitespace-pre-wrap [&_pre]:wrap-break-word [&_table]:block [&_table]:w-fit [&_table]:max-w-full [&_table]:overflow-x-auto";

const PROSE_CLASS =
  "space-y-3 text-muted-foreground text-sm **:leading-relaxed [&_a:hover]:underline [&_a]:text-primary [&_blockquote]:border-muted-foreground/30 [&_blockquote]:border-l-2 [&_blockquote]:pl-3 [&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-xs [&_h1]:mt-4 [&_h1]:font-semibold [&_h1]:text-xl [&_h2]:mt-3 [&_h2]:font-semibold [&_h2]:text-lg [&_h3]:mt-3 [&_h3]:font-semibold [&_h3]:text-base [&_h4]:mt-2 [&_h4]:font-semibold [&_h4]:text-sm [&_h5]:mt-2 [&_h5]:font-medium [&_h5]:text-sm [&_h6]:mt-2 [&_h6]:font-semibold [&_h6]:text-xs [&_hr]:border-border [&_li]:mt-1 [&_ol]:list-decimal [&_ol]:pl-6 [&_pre]:rounded [&_pre]:bg-muted [&_pre]:p-2 [&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_pre_code]:text-inherit [&_strong]:font-semibold [&_td]:border [&_td]:border-border [&_td]:px-2 [&_td]:py-1 [&_th]:border [&_th]:border-border [&_th]:px-2 [&_th]:py-1 [&_th]:font-semibold [&_ul]:list-disc [&_ul]:pl-6";

function handleHashClick(e: MouseEvent<HTMLAnchorElement>) {
  const href = e.currentTarget.getAttribute("href");
  if (!href) return;

  // Walk up to the nearest scrollable ancestor
  let container: HTMLElement | null = e.currentTarget.parentElement;
  while (container) {
    const { overflow, overflowY } = getComputedStyle(container);
    if (
      overflow === "auto" ||
      overflow === "scroll" ||
      overflowY === "auto" ||
      overflowY === "scroll"
    ) {
      break;
    }
    container = container.parentElement;
  }

  const target = (container ?? document).querySelector(href);
  if (target) {
    e.preventDefault();
    target.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

// react-markdown hands every custom component the hast `node`, which is not a
// DOM attribute — it is dropped before the rest of the props reach the element.
type AnchorProps = ComponentPropsWithoutRef<"a"> & { node?: unknown };

function MarkdownAnchor({ node: _node, href, children, ...props }: AnchorProps) {
  if (href?.startsWith("#")) {
    return (
      <a href={href} onClick={handleHashClick} {...props}>
        {children}
      </a>
    );
  }
  return (
    <a href={href} {...props}>
      {children}
    </a>
  );
}

export const Markdown = ({ content, className }: MarkdownProps) => {
  if (!content) {
    return null;
  }
  return (
    <div className={cn(CONTAINMENT_CLASS, PROSE_CLASS, className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSlug]}
        components={{ a: MarkdownAnchor }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
};
