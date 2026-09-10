/**
 * Turning one notification row into a sentence and a destination.
 *
 * Shared by the bell's popover (what is still unread) and the inbox page (the
 * record). One implementation: a line must read the same wherever it is shown,
 * and a second copy is how the two drift apart.
 */
import { useRouter } from "@tanstack/react-router";
import { Bell, CheckCheck, Loader2 } from "lucide-react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { NotificationRead } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { RelativeTime } from "@/components/ui/relative-time";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useAuth } from "@/hooks/useAuth";
import { useNotificationStreamConnected } from "@/hooks/useNotificationStream";
import {
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useNotifications,
} from "@/hooks/useNotifications";
import { normalizeAppTarget, normalizeLegacyTarget } from "@/lib/entityResolver";
import { downloadExportArtifact } from "@/lib/exportDownload";
import { guildPath } from "@/lib/guildUrl";
import { entityRefRoute, TOOLS, toolRefRoute } from "@/lib/tools";

// How often the bell asks on its own, which is only ever when there is no
// channel to ask for it.
const NOTIFICATION_POLL_INTERVAL_MS = 30_000;

// Build guild-scoped URL directly. Notification rows persist their
// target_path, so one written before tools moved inside their initiative is
// mapped onto the `/go` resolver on the way out.
const buildGuildPath = (guildId: number, targetPath: string): string => {
  const normalized = targetPath.startsWith("/") ? targetPath : `/${targetPath}`;
  return guildPath(guildId, normalizeLegacyTarget(normalized));
};

export const resolveSmartLink = (notification: NotificationRead): string | null => {
  const data = notification.data || {};
  const guildValue = data.guild_id;
  const targetValue = data.target_path;

  let guildId: number | null = null;
  if (typeof guildValue === "number") {
    guildId = guildValue;
  } else if (typeof guildValue === "string") {
    const parsed = Number(guildValue);
    guildId = Number.isFinite(parsed) ? parsed : null;
  }

  const targetPath = typeof targetValue === "string" ? targetValue : null;
  if (targetPath) {
    // A `target_path` with a guild belongs inside it. One without belongs to
    // the app: an account notice (`/profile/account`) or the cross-guild task
    // list is about the person rather than any one community, so the server
    // sends no `guild_id` with those. The mobile tap handler has always
    // treated a bare `target_path` as an app-level route; this matches it.
    return guildId !== null ? buildGuildPath(guildId, targetPath) : normalizeAppTarget(targetPath);
  }

  if (typeof data.smart_link === "string" && data.smart_link) {
    try {
      const base = typeof window !== "undefined" ? window.location.origin : "http://localhost";
      const parsed = new URL(data.smart_link, base);
      return `${parsed.pathname}${parsed.search}${parsed.hash}`;
    } catch {
      if (data.smart_link.startsWith("/")) {
        return data.smart_link;
      }
    }
  }

  return null;
};

// The `/go` resolver address for a payload that names its parent generically
// (`entity_type` + `entity_id`), or null when it names nothing recognizable.
const entityRefFromData = (data: Record<string, unknown>): string | null => {
  const entityType = typeof data.entity_type === "string" ? data.entity_type : null;
  const entityId = Number(data.entity_id);
  if (!entityType || !Number.isFinite(entityId)) {
    return null;
  }
  if (entityType === "task") {
    return entityRefRoute("task", entityId);
  }
  const tool = TOOLS.find((candidate) => candidate === entityType);
  return tool ? toolRefRoute(tool, entityId) : null;
};

export const notificationLink = (notification: NotificationRead): string | null => {
  const smartLink = resolveSmartLink(notification);
  if (smartLink) {
    return smartLink;
  }
  const data = notification.data || {};
  switch (notification.type) {
    // These hold ids and nothing else, so they address the `/go` resolver,
    // which reads the entity and works out where it lives.
    case "task_assignment": {
      const taskId = Number(data.task_id);
      if (Number.isFinite(taskId) && data.task_id != null) {
        return entityRefRoute("task", taskId);
      }
      if (typeof data.project_id === "number") {
        return entityRefRoute("project", data.project_id);
      }
      return null;
    }
    case "initiative_added":
      // The initiative list is a section of the guild home now.
      return "/";
    case "project_added":
      if (typeof data.project_id === "number") {
        return entityRefRoute("project", data.project_id);
      }
      return null;
    case "import_ready":
    case "import_failed": {
      // The report lives on the guild's Data settings tab (the jobs table's
      // "View report"). Absolute guild path — the notification names its guild.
      const guildId = Number(data.guild_id);
      return Number.isFinite(guildId) ? buildGuildPath(guildId, "/settings/data") : null;
    }
    case "user_pending_approval":
      return "/settings";
    case "direct_message":
      // The page opens the conversation itself: the thread is read out of this
      // device's own store, so there is nothing for a route param to fetch.
      return "/messages";
    case "mention":
    case "comment_reply":
    case "comment_on_resource":
      if (typeof data.document_id === "number") {
        return entityRefRoute("document", data.document_id);
      }
      return entityRefFromData(data);
    case "post_published":
      if (typeof data.post_id === "number") {
        return entityRefRoute("post", data.post_id);
      }
      return null;
    case "access_grant_requested":
    case "access_grant_approved":
    case "access_grant_denied":
    case "access_grant_revoked":
      // The Access tab serves both requesters (their requests) and approvers
      // (the queue). It's a platform route, not guild-scoped.
      return "/settings/admin/access";
    case "event_invitation":
    case "event_updated":
    case "event_cancelled":
    case "event_rsvp":
    case "event_reminder": {
      const eventId = Number(data.event_id);
      return Number.isFinite(eventId) ? entityRefRoute("event", eventId) : null;
    }
    default:
      return null;
  }
};

// Returns the localized level word, or null when the level is unknown (e.g.
// older notifications written before access_level was included) — callers then
// fall back to a generic, level-less message rather than mislabeling it.
const accessLevelLabel = (
  level: unknown,
  t: (key: string, options?: Record<string, unknown>) => string
): string | null => {
  if (level === "read_write") return t("notifications.accessLevelReadWrite");
  if (level === "read") return t("notifications.accessLevelRead");
  return null;
};

// How many distinct emoji a rolled-up reaction line shows before it stops —
// the sentence names the reactors, the chips on the comment itself are the
// full picture.
const MAX_SHOWN_REACTION_EMOJI = 3;

// A reaction notification rolls up every reaction to the same comment, so the
// line names the most recent reactor, how many others joined them, and the
// emoji used. Rows written before the rollup carry their one reaction in the
// top-level `emoji`/`reactor_name` fields, which read here as a rollup of one.
const reactionSummary = (
  data: Record<string, unknown>
): { reactorName: string | null; emoji: string; others: number } => {
  const text = (value: unknown): string | null =>
    typeof value === "string" && value ? value : null;
  const entries = Array.isArray(data.reactions)
    ? (data.reactions as Array<Record<string, unknown>>)
    : [];

  const names = entries
    .map((entry) => text(entry?.reactor_name))
    .filter((name): name is string => name !== null);
  const emoji = entries
    .map((entry) => text(entry?.emoji))
    .filter((value): value is string => value !== null);

  const reactorName = text(data.reactor_name) ?? names[names.length - 1] ?? null;
  const latestEmoji = text(data.emoji);
  if (emoji.length === 0 && latestEmoji) {
    emoji.push(latestEmoji);
  }

  // `reactor_count` counts everyone the line has rolled up, including people
  // whose reactions have since rolled off the detail it keeps — counting the
  // names here would understate the crowd on a busy comment. Rows written
  // before the roster existed only ever had the names, so they use those.
  const rostered = Number(data.reactor_count);
  const others = Number.isFinite(rostered)
    ? Math.max(rostered - 1, 0)
    : new Set(names.filter((name) => name !== reactorName)).size;

  return {
    reactorName,
    emoji: Array.from(new Set(emoji)).slice(0, MAX_SHOWN_REACTION_EMOJI).join(""),
    others,
  };
};

// A comment notification rolls up every comment on the same thing, so the line
// names who and how many rather than repeating per comment. Rows written before
// the rollup carry only ``commenter_name``, which reads here as a rollup of one.
export const commentSummary = (
  data: Record<string, unknown>
): { name: string; others: number; count: number } => {
  const roster = Array.isArray(data.commenters)
    ? (data.commenters as Array<Record<string, unknown>>)
    : [];
  const names = roster
    .map((entry) => (typeof entry?.name === "string" ? entry.name : null))
    .filter((name): name is string => name !== null);
  const latest = names[names.length - 1] ?? null;
  const name =
    latest ?? (typeof data.commenter_name === "string" ? data.commenter_name : "Someone");
  // `commenter_count` is everyone the line stands for, including people whose
  // entry has rolled off the roster it carries.
  const people = Number(data.commenter_count);
  const others = Number.isFinite(people) ? Math.max(people - 1, 0) : 0;
  const count = Number(data.comment_count);
  return { name, others, count: Number.isFinite(count) ? count : 1 };
};

export const notificationText = (
  notification: NotificationRead,
  t: (key: string, options?: Record<string, unknown>) => string
): string => {
  const data = notification.data || {};
  switch (notification.type) {
    case "task_assignment":
      return t("notifications.taskAssignment", {
        taskTitle: data.task_title ?? "A task",
        projectName: data.project_name ?? "a project",
        assignedBy: data.assigned_by_name
          ? t("notifications.taskAssignmentBy", { name: data.assigned_by_name })
          : "",
      });
    case "initiative_added":
      return t("notifications.initiativeAdded", {
        initiativeName: data.initiative_name ?? "initiative",
      });
    case "project_added":
      return t("notifications.projectAdded", {
        projectName: data.project_name ?? "A project",
        initiativeName: data.initiative_name ?? "an initiative",
      });
    case "user_pending_approval":
      return t("notifications.userPendingApproval", { email: data.email ?? "A user" });
    case "mention":
      // Check if it's a comment mention or document mention
      if (data.comment_id) {
        return t("notifications.mentionComment", {
          mentionedBy: data.mentioned_by_name ?? "Someone",
          contextTitle: data.context_title ?? "an item",
        });
      }
      return t("notifications.mentionDocument", {
        mentionedBy: data.mentioned_by_name ?? "Someone",
        // Notifications stored before the rename still carry `document_title`.
        documentTitle: data.document_name ?? data.document_title ?? "a document",
      });
    case "comment_on_task": {
      const { name, others, count } = commentSummary(data);
      const taskTitle = data.task_title ?? "your task";
      if (count > 1) {
        return others > 0
          ? t("notifications.commentsOnTaskMulti", { name, count, others, taskTitle })
          : t("notifications.commentsOnTask", { name, count, taskTitle });
      }
      return t("notifications.commentOnTask", { commenterName: name, taskTitle });
    }
    case "comment_on_resource": {
      const { name, others, count } = commentSummary(data);
      const entityName = data.entity_name ?? "an item";
      if (count > 1) {
        return others > 0
          ? t("notifications.commentsOnResourceMulti", { name, count, others, entityName })
          : t("notifications.commentsOnResource", { name, count, entityName });
      }
      return t("notifications.commentOnResource", { commenterName: name, entityName });
    }
    case "post_published":
      return t("notifications.postPublished", {
        authorName: data.author_name ?? "Someone",
        postName: data.post_name ?? "a post",
      });
    case "comment_reply":
      return t("notifications.commentReply", {
        replierName: data.replier_name ?? "Someone",
        contextTitle: data.context_title ?? "an item",
      });
    case "direct_message": {
      // Who and how many. There is no preview here and no way to add one --
      // the server has no key to the message it is announcing.
      const count = typeof data.count === "number" ? data.count : 1;
      const senderName = data.sender_name ?? "Someone";
      return count > 1
        ? t("notifications.directMessageMany", { senderName, count })
        : t("notifications.directMessage", { senderName });
    }
    case "comment_reaction": {
      const { reactorName, emoji, others } = reactionSummary(data);
      const options = {
        reactorName: reactorName ?? "Someone",
        emoji,
        contextTitle: data.context_title ?? "an item",
      };
      return others > 0
        ? t("notifications.commentReactionMulti", { ...options, count: others })
        : t("notifications.commentReaction", options);
    }
    case "access_grant_requested": {
      const level = accessLevelLabel(data.access_level, t);
      const requester = data.requester_name ?? "Someone";
      const guild = data.guild_name ?? "a guild";
      return level
        ? t("notifications.accessGrantRequested", { requester, level, guild })
        : t("notifications.accessGrantRequestedGeneric", { requester, guild });
    }
    case "access_grant_approved": {
      const level = accessLevelLabel(data.access_level, t);
      const guild = data.guild_name ?? "a guild";
      return level
        ? t("notifications.accessGrantApproved", { level, guild })
        : t("notifications.accessGrantApprovedGeneric", { guild });
    }
    case "access_grant_denied":
      return t("notifications.accessGrantDenied", { guild: data.guild_name ?? "a guild" });
    case "access_grant_revoked":
      return t("notifications.accessGrantRevoked", { guild: data.guild_name ?? "a guild" });
    case "event_invitation":
      return t("notifications.eventInvitation", {
        organizer: data.organizer_name ?? "Someone",
        eventTitle: data.event_title ?? "an event",
      });
    case "event_updated":
      return data.time_changed
        ? t("notifications.eventRescheduled", {
            editor: data.editor_name ?? "Someone",
            eventTitle: data.event_title ?? "an event",
          })
        : t("notifications.eventUpdated", {
            editor: data.editor_name ?? "Someone",
            eventTitle: data.event_title ?? "an event",
          });
    case "event_cancelled":
      return t("notifications.eventCancelled", {
        canceller: data.canceller_name ?? "Someone",
        eventTitle: data.event_title ?? "an event",
      });
    case "event_rsvp":
      return t("notifications.eventRsvp", {
        responder: data.responder_name ?? "Someone",
        status: data.rsvp_status ?? "responded",
        eventTitle: data.event_title ?? "an event",
      });
    case "event_reminder":
      return t("notifications.eventReminder", {
        eventTitle: data.event_title ?? "an event",
      });
    case "initiative_join_requested":
      return t("notifications.initiativeJoinRequested", {
        requester: data.requester_name ?? "Someone",
        initiativeName: data.initiative_name ?? "an initiative",
      });
    case "initiative_join_approved":
      return t("notifications.initiativeJoinApproved", {
        initiativeName: data.initiative_name ?? "an initiative",
      });
    case "initiative_join_denied":
      return t("notifications.initiativeJoinDenied", {
        initiativeName: data.initiative_name ?? "an initiative",
      });
    case "export_ready":
      return t("notifications.exportReady");
    case "export_failed":
      return t("notifications.exportFailed");
    case "import_ready":
      return t("notifications.importReady");
    case "import_failed":
      return t("notifications.importFailed");
    // What a moderator did to your account. Each says what changed, because
    // the alternative — the generic line — reads as a bug at exactly the
    // moment somebody needs to know what happened to them.
    case "username_changed":
      return t("notifications.usernameChanged", {
        previousHandle: data.previous_handle ?? t("notifications.yourPreviousHandle"),
      });
    case "avatar_removed":
      return t("notifications.avatarRemoved");
    case "account_suspended":
      return typeof data.reason === "string" && data.reason.trim()
        ? t("notifications.accountSuspendedWithReason", { reason: data.reason.trim() })
        : t("notifications.accountSuspended");
    case "account_unsuspended":
      return t("notifications.accountUnsuspended");
    default:
      return t("notifications.defaultNotification");
  }
};

/** Export artifacts are fetched, not navigated to — pull the ids the download
 * call needs, or null when the payload is malformed. */
export const exportDownloadTarget = (
  notification: NotificationRead
): { guildId: number; jobId: number; source: string; format: string } | null => {
  if (notification.type !== "export_ready") {
    return null;
  }
  const data = notification.data || {};
  const guildId = Number(data.guild_id);
  const jobId = Number(data.export_job_id);
  if (!Number.isFinite(guildId) || !Number.isFinite(jobId)) {
    return null;
  }
  return {
    guildId,
    jobId,
    source: typeof data.source === "string" ? data.source : "tasks",
    format: typeof data.format === "string" ? data.format : "pdf",
  };
};
