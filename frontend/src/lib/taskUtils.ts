import type { TaskListRead, TaskRead } from "@/api/generated/initiativeAPI.schemas";

/**
 * Project the ``TaskRead`` detail shape onto the denormalized ``TaskListRead``
 * list row, deriving the list-only fields from the nested guild/project
 * summaries. Task mutation endpoints respond with ``TaskRead``, so surfaces
 * that hold list rows use this to apply a response without dropping the
 * denormalized fields.
 */
export const taskReadToListRow = (task: TaskRead): TaskListRead => {
  const { creator: _creator, guild, project, ...rest } = task;
  return {
    ...rest,
    guild_id: guild?.id ?? null,
    guild_name: guild?.name ?? null,
    project_name: project?.name ?? null,
    initiative_id: project?.initiative_id ?? null,
    initiative_name: project?.initiative?.name ?? null,
    initiative_color: project?.initiative?.color ?? null,
  };
};
