import type { TaskListRead, TaskRead } from "@/api/generated/initiativeAPI.schemas";

/**
 * Project the ``TaskRead`` detail shape onto the denormalized ``TaskListRead``
 * list row, deriving the list-only fields from the nested project summary.
 * Task mutation endpoints respond with ``TaskRead``, so surfaces that hold
 * list rows use this to apply a response without dropping the denormalized
 * fields. ``guildId`` is the guild the page is in, which is what the guild's
 * own list rows carry; ``previous`` is the row being replaced, if any.
 */
export const taskReadToListRow = (
  task: TaskRead,
  guildId: number,
  previous?: TaskListRead
): TaskListRead => {
  const { creator: _creator, project, description, ...rest } = task;
  return {
    ...rest,
    // A list row's excerpt is made by the server, so the row keeps the one it
    // replaces until the list is read again.
    description_excerpt: description ? (previous?.description_excerpt ?? null) : null,
    has_description: Boolean(description),
    community_id: guildId,
    community_name: null,
    project_name: project?.name ?? null,
    initiative_id: project?.initiative_id ?? null,
    initiative_name: project?.initiative?.name ?? null,
    initiative_color: project?.initiative?.color ?? null,
  };
};
