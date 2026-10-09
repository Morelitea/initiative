import { authHandlers } from "./auth.handlers";
import { commentHandlers } from "./comment.handlers";
import { communityHandlers } from "./community.handlers";
import { dmHandlers } from "./dm.handlers";
import { fileHandlers } from "./file.handlers";
import { initiativeHandlers } from "./initiative.handlers";
import { notificationHandlers } from "./notification.handlers";
import { projectHandlers } from "./project.handlers";
import { propertyHandlers } from "./property.handlers";
import { tagHandlers } from "./tag.handlers";
import { taskHandlers } from "./task.handlers";
import { toolCountHandlers } from "./toolCount.handlers";
import { toolViewHandlers } from "./toolView.handlers";
import { userHandlers } from "./user.handlers";
import { versionHandlers } from "./version.handlers";

export const handlers = [
  ...authHandlers,
  ...communityHandlers,
  ...initiativeHandlers,
  ...projectHandlers,
  ...toolViewHandlers,
  ...taskHandlers,
  ...tagHandlers,
  ...fileHandlers,
  ...commentHandlers,
  ...userHandlers,
  ...propertyHandlers,
  ...dmHandlers,
  ...toolCountHandlers,
  ...notificationHandlers,
  ...versionHandlers,
];
