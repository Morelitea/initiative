import { authHandlers } from "./auth.handlers";
import { guildHandlers } from "./guild.handlers";
import { initiativeHandlers } from "./initiative.handlers";
import { projectHandlers } from "./project.handlers";
import { taskHandlers } from "./task.handlers";
import { tagHandlers } from "./tag.handlers";
import { settingsHandlers } from "./settings.handlers";
import { documentHandlers } from "./document.handlers";
import { userHandlers } from "./user.handlers";

export const handlers = [
  ...authHandlers,
  ...guildHandlers,
  ...initiativeHandlers,
  ...projectHandlers,
  ...taskHandlers,
  ...tagHandlers,
  ...settingsHandlers,
  ...documentHandlers,
  ...userHandlers,
];
