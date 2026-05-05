import type { AnchorHTMLAttributes, MouseEvent } from "react";
import ReactMarkdown from "react-markdown";
import rehypeSlug from "rehype-slug";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils";

interface MarkdownProps {
  content: string;
  className?: string;
}

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

function MarkdownAnchor({ href, children, ...props }: AnchorHTMLAttributes<HTMLAnchorElement>) {
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
    <div
      className={cn(
        "text-muted-foreground [&_a]:text-primary space-y-3 text-sm wrap-break-word **:leading-relaxed [&_a]:break-all [&_a:hover]:underline [&_h1]:mt-4 [&_h1]:text-xl [&_h1]:font-semibold [&_h2]:mt-3 [&_h2]:text-lg [&_h2]:font-semibold [&_h3]:mt-3 [&_h3]:text-base [&_h3]:font-semibold [&_h4]:mt-2 [&_h4]:text-sm [&_h4]:font-semibold [&_h5]:mt-2 [&_h5]:text-sm [&_h5]:font-medium [&_h6]:mt-2 [&_h6]:text-xs [&_h6]:font-semibold [&_li]:mt-1 [&_ol]:list-decimal [&_ol]:pl-6 [&_strong]:font-semibold [&_ul]:list-disc [&_ul]:pl-6",
        className
      )}
    >
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
