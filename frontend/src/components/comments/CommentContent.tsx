import { Fragment, useMemo } from "react";
import { Link } from "react-router-dom";

import { useGuilds } from "@/hooks/useGuilds";

interface MentionPart {
  type: "text" | "user" | "task" | "doc" | "project";
  content: string;
  id?: number;
}

// Patterns for parsing mentions
const USER_PATTERN = /@\{(\d+)\}/g;
const TASK_PATTERN = /#task:(\d+)/g;
const DOC_PATTERN = /#doc:(\d+)/g;
const PROJECT_PATTERN = /#project:(\d+)/g;

interface ParsedMention {
  type: "user" | "task" | "doc" | "project";
  id: number;
  start: number;
  end: number;
  raw: string;
}

function parseContent(content: string): MentionPart[] {
  const mentions: ParsedMention[] = [];

  // Find all mentions
  let match: RegExpExecArray | null;

  USER_PATTERN.lastIndex = 0;
  while ((match = USER_PATTERN.exec(content)) !== null) {
    mentions.push({
      type: "user",
      id: parseInt(match[1], 10),
      start: match.index,
      end: match.index + match[0].length,
      raw: match[0],
    });
  }

  TASK_PATTERN.lastIndex = 0;
  while ((match = TASK_PATTERN.exec(content)) !== null) {
    mentions.push({
      type: "task",
      id: parseInt(match[1], 10),
      start: match.index,
      end: match.index + match[0].length,
      raw: match[0],
    });
  }

  DOC_PATTERN.lastIndex = 0;
  while ((match = DOC_PATTERN.exec(content)) !== null) {
    mentions.push({
      type: "doc",
      id: parseInt(match[1], 10),
      start: match.index,
      end: match.index + match[0].length,
      raw: match[0],
    });
  }

  PROJECT_PATTERN.lastIndex = 0;
  while ((match = PROJECT_PATTERN.exec(content)) !== null) {
    mentions.push({
      type: "project",
      id: parseInt(match[1], 10),
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

  return parts;
}

interface CommentContentProps {
  content: string;
  userDisplayNames?: Map<number, string>;
  taskTitles?: Map<number, string>;
  docTitles?: Map<number, string>;
  projectNames?: Map<number, string>;
}

export const CommentContent = ({
  content,
  userDisplayNames = new Map(),
  taskTitles = new Map(),
  docTitles = new Map(),
  projectNames = new Map(),
}: CommentContentProps) => {
  const { activeGuildId } = useGuilds();
  const guildId = activeGuildId;

  const parts = useMemo(() => parseContent(content), [content]);

  const buildSmartLink = (targetPath: string) => {
    if (!guildId) return targetPath;
    return `/navigate?guild_id=${guildId}&target=${encodeURIComponent(targetPath)}`;
  };

  return (
    <span className="whitespace-pre-wrap">
      {parts.map((part, index) => {
        if (part.type === "text") {
          return <Fragment key={index}>{part.content}</Fragment>;
        }

        if (part.type === "user") {
          const displayName = userDisplayNames.get(part.id!) || `User #${part.id}`;
          return (
            <span
              key={index}
              className="bg-primary/10 text-primary rounded px-1 py-0.5 text-sm font-medium"
            >
              @{displayName}
            </span>
          );
        }

        if (part.type === "task") {
          const title = taskTitles.get(part.id!) || `Task #${part.id}`;
          return (
            <Link
              key={index}
              to={buildSmartLink(`/tasks/${part.id}`)}
              className="text-primary hover:underline"
            >
              Task: {title}
            </Link>
          );
        }

        if (part.type === "doc") {
          const title = docTitles.get(part.id!) || `Document #${part.id}`;
          return (
            <Link
              key={index}
              to={buildSmartLink(`/documents/${part.id}`)}
              className="text-primary hover:underline"
            >
              Doc: {title}
            </Link>
          );
        }

        if (part.type === "project") {
          const name = projectNames.get(part.id!) || `Project #${part.id}`;
          return (
            <Link
              key={index}
              to={buildSmartLink(`/projects/${part.id}`)}
              className="text-primary hover:underline"
            >
              Project: {name}
            </Link>
          );
        }

        return <Fragment key={index}>{part.content}</Fragment>;
      })}
    </span>
  );
};
