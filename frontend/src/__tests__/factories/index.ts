export { buildComment, resetCounter as resetCommentCounter } from "./comment.factory";
export { buildDocumentSummary, resetCounter as resetDocumentCounter } from "./document.factory";
export {
  buildGuild,
  buildGuildInviteStatus,
  resetCounter as resetGuildCounter,
} from "./guild.factory";
export {
  buildInitiative,
  buildInitiativeMember,
  resetCounter as resetInitiativeCounter,
} from "./initiative.factory";
export {
  buildNotification,
  resetCounter as resetNotificationCounter,
} from "./notification.factory";
export {
  buildDefaultTaskStatuses,
  buildProject,
  buildProjectPermission,
  buildProjectTaskStatus,
  resetCounter as resetProjectCounter,
} from "./project.factory";
export {
  buildPropertyDefinition,
  buildPropertyOption,
  buildPropertySummary,
  resetCounter as resetPropertyCounter,
} from "./properties";
export {
  buildQueue,
  buildQueueItem,
  buildQueueListResponse,
  buildQueuePermission,
  buildQueueRolePermission,
  buildQueueSummary,
  resetCounter as resetQueueCounter,
} from "./queue.factory";
export {
  buildRecentCounterGroupItem,
  buildRecentDocumentItem,
  buildRecentItem,
  buildRecentProjectItem,
  buildRecentQueueItem,
  resetRecentCounter,
} from "./recent.factory";
export { buildTag, buildTagSummary, resetCounter as resetTagCounter } from "./tag.factory";
export {
  buildTask,
  buildTaskAssignee,
  buildTaskListResponse,
  resetCounter as resetTaskCounter,
} from "./task.factory";
export {
  buildUser,
  buildUserGuildMember,
  buildUserPublic,
  resetCounter as resetUserCounter,
} from "./user.factory";

import { resetCounter as resetCommentCounter } from "./comment.factory";
import { resetCounter as resetDocumentCounter } from "./document.factory";
import { resetCounter as resetGuildCounter } from "./guild.factory";
import { resetCounter as resetInitiativeCounter } from "./initiative.factory";
import { resetCounter as resetNotificationCounter } from "./notification.factory";
import { resetCounter as resetProjectCounter } from "./project.factory";
import { resetCounter as resetPropertyCounter } from "./properties";
import { resetCounter as resetQueueCounter } from "./queue.factory";
import { resetRecentCounter } from "./recent.factory";
import { resetCounter as resetTagCounter } from "./tag.factory";
import { resetCounter as resetTaskCounter } from "./task.factory";
import { resetCounter as resetUserCounter } from "./user.factory";

/**
 * Resets all factory counters back to 0.
 * Call this in beforeEach() to ensure deterministic IDs across tests.
 */
export function resetFactories(): void {
  resetUserCounter();
  resetGuildCounter();
  resetInitiativeCounter();
  resetProjectCounter();
  resetTaskCounter();
  resetTagCounter();
  resetDocumentCounter();
  resetCommentCounter();
  resetNotificationCounter();
  resetQueueCounter();
  resetPropertyCounter();
  resetRecentCounter();
}
