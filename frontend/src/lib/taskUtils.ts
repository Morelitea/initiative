import type { TaskListRead, TaskRead } from "@/api/generated/initiativeAPI.schemas";

/**
 * Project the ``TaskRead`` detail shape onto the denormalized ``TaskListRead``
 * list row, deriving the list-only fields from the nested project summary.
 * Task mutation endpoints respond with ``TaskRead``, so surfaces that hold
 * list rows use this to apply a response without dropping the denormalized
 * fields. ``guildId`` is the guild the page is in, which is what the guild's
 * own list rows carry.
 */
export const taskReadToListRow = (task: TaskRead, guildId: number): TaskListRead => {
  const { creator: _creator, project, ...rest } = task;
  return {
    ...rest,
    guild_id: guildId,
    guild_name: null,
    project_name: project?.name ?? null,
    initiative_id: project?.initiative_id ?? null,
    initiative_name: project?.initiative?.name ?? null,
    initiative_color: project?.initiative?.color ?? null,
  };
};
