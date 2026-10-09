import type { TaskListRead } from "@/api/generated/initiativeAPI.schemas";
import { defineSection } from "@/lib/templates/sections";
import type { ShapeTable } from "@/lib/templates/shapes";

/**
 * Enough of the API's task schema for the template tests, in the shape
 * `schemaShapes.json` holds. That file carries only what real sections read,
 * so the tests bring their own.
 */
export const TASK_SHAPES: ShapeTable = {
  TaskListRead: {
    fields: {
      id: "number",
      title: "string",
      priority: { ref: "TaskPriority" },
      due_date: "string",
      assignees: { list: { ref: "UserPublic" } },
      task_status: { ref: "TaskStatusRead" },
    },
  },
  TaskPriority: { enum: ["low", "medium", "high", "urgent"] },
  UserPublic: { fields: { id: "number", display_name: "string" } },
  TaskStatusRead: { fields: { name: "string", category: { ref: "TaskStatusCategory" } } },
  TaskStatusCategory: { enum: ["backlog", "todo", "in_progress", "done"] },
};

/** A card section for the tests: a required title and an optional checklist. */
export const taskCardSection = defineSection<{ task: TaskListRead }>()({
  data: { task: "TaskListRead" },
  parts: { title: { required: true }, checklist: {} },
});
