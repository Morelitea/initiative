import { Link } from "@tanstack/react-router";
import type { ComponentPropsWithoutRef, Ref } from "react";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { useGuilds } from "@/hooks/useGuilds";
import { guildPath } from "@/lib/guildUrl";
import { entityRefRoute } from "@/lib/tools";
import { cn } from "@/lib/utils";

import { type MentionType, remarkLineBreaks, remarkMentions } from "./remarkCommentPlugins";

interface CommentContentProps {
  content: string;
  /** Drops block spacing so the body can sit in a clamped preview. */
  compact?: boolean;
  /** Renders mentions and urls as plain text. Set it when the body itself
   *  sits inside a link, which cannot legally contain one. */
  disableLinks?: boolean;
  className?: string;
  ref?: Ref<HTMLDivElement>;
}

/** Mention kinds that address an entity: which ref type resolves them, and
 *  the label the link renders under. */
const MENTION_REFS = {
  task: { refType: "task", labelKey: "comments.taskPrefix" },
  doc: { refType: "document", labelKey: "comments.docPrefix" },
  project: { refType: "project", labelKey: "comments.projectPrefix" },
} as const;

const PROSE_CLASS =
  "wrap-break-word text-sm [&_a:hover]:underline [&_a]:break-all [&_a]:text-primary [&_blockquote]:border-muted-foreground/30 [&_blockquote]:border-l-2 [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground [&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-xs [&_h1]:font-semibold [&_h1]:text-base [&_h2]:font-semibold [&_h2]:text-base [&_h3]:font-semibold [&_h3]:text-sm [&_h4]:font-semibold [&_h4]:text-sm [&_h5]:font-semibold [&_h5]:text-sm [&_h6]:font-semibold [&_h6]:text-sm [&_hr]:border-border [&_li]:mt-0.5 [&_ol]:list-decimal [&_ol]:pl-5 [&_pre]:overflow-x-auto [&_pre]:rounded [&_pre]:bg-muted [&_pre]:p-2 [&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_strong]:font-semibold [&_table]:block [&_table]:w-fit [&_table]:overflow-x-auto [&_td]:border [&_td]:border-border [&_td]:px-2 [&_td]:py-1 [&_th]:border [&_th]:border-border [&_th]:px-2 [&_th]:py-1 [&_th]:font-semibold [&_ul]:list-disc [&_ul]:pl-5";

const SPACED_CLASS = "[&>*+*]:mt-2 [&_h1]:mt-3 [&_h2]:mt-3 [&_h3]:mt-2";

type SpanProps = ComponentPropsWithoutRef<"span"> & { node?: unknown };
type AnchorProps = ComponentPropsWithoutRef<"a"> & { node?: unknown };

const MENTION_BADGE = "rounded bg-primary/10 px-1 py-0.5 font-medium text-primary text-sm";

/** Mentions reach here as spans carrying their type, id, and label — the shape
 *  `remarkMentions` folds them into. Every other span passes through. */
const buildMentionSpan = (linked: boolean) =>
  function MentionSpan({ children, node: _node, ...props }: SpanProps) {
    const { t } = useTranslation("documents");
    const { activeGuildId } = useGuilds();

    const attrs = props as Record<string, string | undefined>;
    const type = attrs["data-mention-type"] as MentionType | undefined;
    const id = attrs["data-mention-id"];
    const label = attrs["data-mention-label"] ?? "";

    if (!type) {
      return <span {...props}>{children}</span>;
    }

    if (type === "user") {
      return <span className={MENTION_BADGE}>@{label}</span>;
    }

    // A mention carries only an id, and an entity's address names its
    // initiative — so these link at the `/go` resolver, which reads the entity
    // and redirects. An id-less mention renders as plain text rather than a
    // link that resolves to nothing.
    const ref = MENTION_REFS[type];
    if (!ref || !id) {
      return <span>{label}</span>;
    }

    const text = t(ref.labelKey, { name: label });
    if (!linked) {
      return <span className={MENTION_BADGE}>{text}</span>;
    }

    // Build a guild-scoped link directly instead of using the /navigate redirect.
    const path = entityRefRoute(ref.refType, Number(id));
    return (
      <Link
        to={activeGuildId ? guildPath(activeGuildId, path) : path}
        className="text-primary hover:underline"
      >
        {text}
      </Link>
    );
  };

const MarkdownAnchor = ({ children, node: _node, ...props }: AnchorProps) => (
  <a {...props} target="_blank" rel="noopener noreferrer">
    {children}
  </a>
);

const PlainAnchor = ({ children }: AnchorProps) => <span>{children}</span>;

const LINKED_COMPONENTS = { span: buildMentionSpan(true), a: MarkdownAnchor };
const PLAIN_COMPONENTS = { span: buildMentionSpan(false), a: PlainAnchor };
const PLUGINS = [remarkGfm, remarkMentions, remarkLineBreaks];

export const CommentContent = ({
  content,
  compact = false,
  disableLinks = false,
  className,
  ref,
}: CommentContentProps) => (
  <div ref={ref} className={cn(PROSE_CLASS, !compact && SPACED_CLASS, className)}>
    <ReactMarkdown
      remarkPlugins={PLUGINS}
      components={disableLinks ? PLAIN_COMPONENTS : LINKED_COMPONENTS}
    >
      {content}
    </ReactMarkdown>
  </div>
);
