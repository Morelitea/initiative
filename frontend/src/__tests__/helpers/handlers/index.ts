import { authHandlers } from "./auth.handlers";
import { commentHandlers } from "./comment.handlers";
import { dmHandlers } from "./dm.handlers";
import { documentHandlers } from "./document.handlers";
import { filterPresetHandlers } from "./filterPreset.handlers";
import { guildHandlers } from "./guild.handlers";
import { initiativeHandlers } from "./initiative.handlers";
import { projectHandlers } from "./project.handlers";
import { propertyHandlers } from "./property.handlers";
import { settingsHandlers } from "./settings.handlers";
import { tagHandlers } from "./tag.handlers";
import { taskHandlers } from "./task.handlers";
import { toolCountHandlers } from "./toolCount.handlers";
import { userHandlers } from "./user.handlers";

export const handlers = [
  ...authHandlers,
  ...guildHandlers,
  ...initiativeHandlers,
  ...projectHandlers,
  ...filterPresetHandlers,
  ...taskHandlers,
  ...tagHandlers,
  ...settingsHandlers,
  ...documentHandlers,
  ...commentHandlers,
  ...userHandlers,
  ...propertyHandlers,
  ...dmHandlers,
  ...toolCountHandlers,
];
