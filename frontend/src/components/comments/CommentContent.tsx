import type { ComponentPropsWithoutRef, Ref } from "react";
import ReactMarkdown, { type Options } from "react-markdown";
import remarkGfm from "remark-gfm";

import { ImageLightboxScope, InLink, ProseImage } from "@/components/markdown/ProseImage";
import { isStoredUpload, remarkImageLinks, remarkLineBreaks } from "@/lib/remarkProse";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import { cn } from "@/lib/utils";

import { LinkedMentionSpan, PlainMentionSpan } from "./MentionSpan";
import { remarkMentions } from "./remarkCommentPlugins";

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

const PROSE_CLASS =
  "wrap-break-word text-sm [&_a:hover]:underline [&_a]:break-all [&_a]:text-primary [&_blockquote]:border-muted-foreground/30 [&_blockquote]:border-l-2 [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground [&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-xs [&_h1]:font-semibold [&_h1]:text-base [&_h2]:font-semibold [&_h2]:text-base [&_h3]:font-semibold [&_h3]:text-sm [&_h4]:font-semibold [&_h4]:text-sm [&_h5]:font-semibold [&_h5]:text-sm [&_h6]:font-semibold [&_h6]:text-sm [&_hr]:border-border [&_li]:mt-0.5 [&_ol]:list-decimal [&_ol]:pl-5 [&_pre]:overflow-x-auto [&_pre]:rounded [&_pre]:bg-muted [&_pre]:p-2 [&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_strong]:font-semibold [&_table]:block [&_table]:w-fit [&_table]:overflow-x-auto [&_td]:border [&_td]:border-border [&_td]:px-2 [&_td]:py-1 [&_th]:border [&_th]:border-border [&_th]:px-2 [&_th]:py-1 [&_th]:font-semibold [&_ul]:list-disc [&_ul]:pl-5";

const SPACED_CLASS = "[&>*+*]:mt-2 [&_h1]:mt-3 [&_h2]:mt-3 [&_h3]:mt-2";

type AnchorProps = ComponentPropsWithoutRef<"a"> & { node?: unknown };
type ImageProps = ComponentPropsWithoutRef<"img"> & { node?: unknown };

const MarkdownAnchor = ({ children, node: _node, ...props }: AnchorProps) => (
  <a {...props} target="_blank" rel="noopener noreferrer">
    <InLink>{children}</InLink>
  </a>
);

const PlainAnchor = ({ children }: AnchorProps) => <span>{children}</span>;

/** A picture by its name — for a clamped preview, and for any image that is
 *  not one this app stores (`remarkImageLinks` makes those links, so reaching
 *  here means an unexpected shape). */
const ImageName = ({ src, alt }: ImageProps) => (
  <span>{alt || (typeof src === "string" ? src : "")}</span>
);

/** A picture pasted into the comment, fetched from the server it is stored on. */
const StoredImage = (props: ImageProps) => {
  const { src, alt, title } = props;
  if (typeof src !== "string" || !isStoredUpload(src)) return <ImageName {...props} />;
  return (
    <ProseImage
      src={resolveUploadUrl(src) ?? src}
      alt={alt ?? ""}
      title={title}
      className="max-h-80 rounded-md border border-border"
    />
  );
};

const LINKED_COMPONENTS = { span: LinkedMentionSpan, a: MarkdownAnchor, img: StoredImage };
const PLAIN_COMPONENTS = { span: PlainMentionSpan, a: PlainAnchor, img: StoredImage };
const COMPACT_LINKED_COMPONENTS = { ...LINKED_COMPONENTS, img: ImageName };
const COMPACT_PLAIN_COMPONENTS = { ...PLAIN_COMPONENTS, img: ImageName };
// Mentions resolve before images, so an image-derived link is never mistaken
// for one. A picture stored here stays a picture; one from anywhere else
// becomes a link, so reading a comment never fetches from a site nobody chose.
const PLUGINS = [
  remarkGfm,
  remarkMentions,
  [remarkImageLinks, { keep: isStoredUpload }],
  remarkLineBreaks,
] satisfies Options["remarkPlugins"];

export const CommentContent = ({
  content,
  compact = false,
  disableLinks = false,
  className,
  ref,
}: CommentContentProps) => {
  const rendered = (
    <div ref={ref} className={cn(PROSE_CLASS, !compact && SPACED_CLASS, className)}>
      <ReactMarkdown
        remarkPlugins={PLUGINS}
        components={
          compact
            ? disableLinks
              ? COMPACT_PLAIN_COMPONENTS
              : COMPACT_LINKED_COMPONENTS
            : disableLinks
              ? PLAIN_COMPONENTS
              : LINKED_COMPONENTS
        }
      >
        {content}
      </ReactMarkdown>
    </div>
  );
  // A body that sits inside a link leaves the click to it.
  return disableLinks ? rendered : <ImageLightboxScope>{rendered}</ImageLightboxScope>;
};
