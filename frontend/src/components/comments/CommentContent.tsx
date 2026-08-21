import { Link } from "@tanstack/react-router";
import { Fragment, useMemo } from "react";
import { useTranslation } from "react-i18next";

import { useGuilds } from "@/hooks/useGuilds";
import { guildPath } from "@/lib/guildUrl";
import { entityRefRoute } from "@/lib/tools";

interface MentionPart {
  type: "text" | "user" | "task" | "doc" | "project" | "url";
  content: string;
  id?: number;
  displayText?: string;
  url?: string;
}

// Patterns for parsing mentions with embedded display text
// Format: @[Display Name](id) or #type[Display Text](id)
const USER_PATTERN = /@\[([^\]]+)\]\((\d+)\)/g;
const TASK_PATTERN = /#task\[([^\]]+)\]\((\d+)\)/g;
const DOC_PATTERN = /#doc\[([^\]]+)\]\((\d+)\)/g;
const PROJECT_PATTERN = /#project\[([^\]]+)\]\((\d+)\)/g;
// URL pattern - matches http://, https://, and www. URLs
const URL_PATTERN = /(?:https?:\/\/|www\.)[^\s<>"{}|\\^`[\]]+/gi;

interface ParsedMention {
  type: "user" | "task" | "doc" | "project";
  id: number;
  displayText: string;
  start: number;
  end: number;
  raw: string;
}

function parseContent(content: string): MentionPart[] {
  const mentions: ParsedMention[] = [];

  const collectMatches = (pattern: RegExp, type: ParsedMention["type"]) => {
    pattern.lastIndex = 0;
    let match = pattern.exec(content);
    while (match !== null) {
      mentions.push({
        type,
        displayText: match[1],
        id: parseInt(match[2], 10),
        start: match.index,
        end: match.index + match[0].length,
        raw: match[0],
      });
      match = pattern.exec(content);
    }
  };

  collectMatches(USER_PATTERN, "user");
  collectMatches(TASK_PATTERN, "task");
  collectMatches(DOC_PATTERN, "doc");
  collectMatches(PROJECT_PATTERN, "project");

  // Sort by position
  mentions.sort((a, b) => a.start - b.start);

  // Build parts array
  const parts: MentionPart[] = [];
  let lastIndex = 0;

  for (const mention of mentions) {
    // Add text before this mention
    if (mention.start > lastIndex) {
      parts.push({
        type: "text",
        content: content.slice(lastIndex, mention.start),
      });
    }

    // Add the mention
    parts.push({
      type: mention.type,
      content: mention.raw,
      id: mention.id,
      displayText: mention.displayText,
    });

    lastIndex = mention.end;
  }

  // Add remaining text
  if (lastIndex < content.length) {
    parts.push({
      type: "text",
      content: content.slice(lastIndex),
    });
  }

  // Now parse URLs in text parts
  const partsWithUrls: MentionPart[] = [];
  for (const part of parts) {
    if (part.type !== "text") {
      partsWithUrls.push(part);
      continue;
    }

    // Find URLs in this text segment
    const text = part.content;
    const urlMatches: { url: string; start: number; end: number }[] = [];

    URL_PATTERN.lastIndex = 0;
    let urlMatch = URL_PATTERN.exec(text);
    while (urlMatch !== null) {
      // Strip trailing punctuation that's likely sentence punctuation, not part of the URL
      let url = urlMatch[0];
      const trailingPunctuation = /[.,;:!?)\]]+$/;
      const trailingMatch = url.match(trailingPunctuation);
      if (trailingMatch) {
        url = url.slice(0, -trailingMatch[0].length);
      }
      urlMatches.push({
        url,
        start: urlMatch.index,
        end: urlMatch.index + url.length,
      });
      urlMatch = URL_PATTERN.exec(text);
    }

    if (urlMatches.length === 0) {
      partsWithUrls.push(part);
      continue;
    }

    // Split text by URLs
    let textIndex = 0;
    for (const urlInfo of urlMatches) {
      if (urlInfo.start > textIndex) {
        partsWithUrls.push({
          type: "text",
          content: text.slice(textIndex, urlInfo.start),
        });
      }
      partsWithUrls.push({
        type: "url",
        content: urlInfo.url,
        url: urlInfo.url.startsWith("www.") ? `https://${urlInfo.url}` : urlInfo.url,
      });
      textIndex = urlInfo.end;
    }
    if (textIndex < text.length) {
      partsWithUrls.push({
        type: "text",
        content: text.slice(textIndex),
      });
    }
  }

  return partsWithUrls;
}

interface CommentContentProps {
  content: string;
}

/** Mention kinds that address an entity: which ref type resolves them, and
 *  the label the link renders under. */
const MENTION_REFS = {
  task: { refType: "task", labelKey: "comments.taskPrefix" },
  doc: { refType: "document", labelKey: "comments.docPrefix" },
  project: { refType: "project", labelKey: "comments.projectPrefix" },
} as const;

export const CommentContent = ({ content }: CommentContentProps) => {
  const { t } = useTranslation("documents");
  const { activeGuildId } = useGuilds();
  const guildId = activeGuildId;

  const parts = useMemo(() => parseContent(content), [content]);

  // Build guild-scoped link directly instead of using /navigate redirect
  const gp = (path: string) => (guildId ? guildPath(guildId, path) : path);

  return (
    <span className="wrap-break-word whitespace-pre-wrap">
      {parts.map((part, index) => {
        if (part.type === "text") {
          // biome-ignore lint/suspicious/noArrayIndexKey: no id to key from, just parts of a string
          return <Fragment key={index}>{part.content}</Fragment>;
        }

        if (part.type === "url") {
          return (
            <a
              // biome-ignore lint/suspicious/noArrayIndexKey: no id to key from, just parts of a string
              key={index}
              href={part.url}
              target="_blank"
              rel="noopener noreferrer"
              className="break-all text-primary hover:underline"
            >
              {part.content}
            </a>
          );
        }

        if (part.type === "user") {
          return (
            <span
              // biome-ignore lint/suspicious/noArrayIndexKey: no id to key from, just parts of a string
              key={index}
              className="rounded bg-primary/10 px-1 py-0.5 font-medium text-primary text-sm"
            >
              @{part.displayText}
            </span>
          );
        }

        // A mention carries only an id, and an entity's address names its
        // initiative — so these link at the `/go` resolver, which reads the
        // entity and redirects. An id-less mention renders as plain text
        // rather than a link that resolves to nothing.
        if (MENTION_REFS[part.type as keyof typeof MENTION_REFS] && part.id !== undefined) {
          const { refType, labelKey } = MENTION_REFS[part.type as keyof typeof MENTION_REFS];
          return (
            <Link
              // biome-ignore lint/suspicious/noArrayIndexKey: no id to key from, just parts of a string
              key={index}
              to={gp(entityRefRoute(refType, part.id))}
              className="text-primary hover:underline"
            >
              {t(labelKey, { name: part.displayText })}
            </Link>
          );
        }
        // biome-ignore lint/suspicious/noArrayIndexKey: no id to key from, just parts of a string
        return <Fragment key={index}>{part.content}</Fragment>;
      })}
    </span>
  );
};
