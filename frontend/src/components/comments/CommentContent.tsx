import { Fragment, useMemo } from "react";
import { Link } from "react-router-dom";

import { useGuilds } from "@/hooks/useGuilds";

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

  // Find all mentions with new format (with display text)
  let match: RegExpExecArray | null;

  USER_PATTERN.lastIndex = 0;
  while ((match = USER_PATTERN.exec(content)) !== null) {
    mentions.push({
      type: "user",
      displayText: match[1],
      id: parseInt(match[2], 10),
      start: match.index,
      end: match.index + match[0].length,
      raw: match[0],
    });
  }

  TASK_PATTERN.lastIndex = 0;
  while ((match = TASK_PATTERN.exec(content)) !== null) {
    mentions.push({
      type: "task",
      displayText: match[1],
      id: parseInt(match[2], 10),
      start: match.index,
      end: match.index + match[0].length,
      raw: match[0],
    });
  }

  DOC_PATTERN.lastIndex = 0;
  while ((match = DOC_PATTERN.exec(content)) !== null) {
    mentions.push({
      type: "doc",
      displayText: match[1],
      id: parseInt(match[2], 10),
      start: match.index,
      end: match.index + match[0].length,
      raw: match[0],
    });
  }

  PROJECT_PATTERN.lastIndex = 0;
  while ((match = PROJECT_PATTERN.exec(content)) !== null) {
    mentions.push({
      type: "project",
      displayText: match[1],
      id: parseInt(match[2], 10),
      start: match.index,
      end: match.index + match[0].length,
      raw: match[0],
    });
  }

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
    let urlMatch: RegExpExecArray | null;
    while ((urlMatch = URL_PATTERN.exec(text)) !== null) {
      urlMatches.push({
        url: urlMatch[0],
        start: urlMatch.index,
        end: urlMatch.index + urlMatch[0].length,
      });
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

export const CommentContent = ({ content }: CommentContentProps) => {
  const { activeGuildId } = useGuilds();
  const guildId = activeGuildId;

  const parts = useMemo(() => parseContent(content), [content]);

  const buildSmartLink = (targetPath: string) => {
    if (!guildId) return targetPath;
    return `/navigate?guild_id=${guildId}&target=${encodeURIComponent(targetPath)}`;
  };

  return (
    <span className="break-words whitespace-pre-wrap">
      {parts.map((part, index) => {
        if (part.type === "text") {
          return <Fragment key={index}>{part.content}</Fragment>;
        }

        if (part.type === "url") {
          return (
            <a
              key={index}
              href={part.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary break-all hover:underline"
            >
              {part.content}
            </a>
          );
        }

        if (part.type === "user") {
          return (
            <span
              key={index}
              className="bg-primary/10 text-primary rounded px-1 py-0.5 text-sm font-medium"
            >
              @{part.displayText}
            </span>
          );
        }

        if (part.type === "task") {
          return (
            <Link
              key={index}
              to={buildSmartLink(`/tasks/${part.id}`)}
              className="text-primary hover:underline"
            >
              Task: {part.displayText}
            </Link>
          );
        }

        if (part.type === "doc") {
          return (
            <Link
              key={index}
              to={buildSmartLink(`/documents/${part.id}`)}
              className="text-primary hover:underline"
            >
              Doc: {part.displayText}
            </Link>
          );
        }

        if (part.type === "project") {
          return (
            <Link
              key={index}
              to={buildSmartLink(`/projects/${part.id}`)}
              className="text-primary hover:underline"
            >
              Project: {part.displayText}
            </Link>
          );
        }

        return <Fragment key={index}>{part.content}</Fragment>;
      })}
    </span>
  );
};
