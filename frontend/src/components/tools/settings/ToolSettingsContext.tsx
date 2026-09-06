/**
 * What a tool's settings sections read.
 *
 * The sections are routes now, so the tool wrapper that fetches the entity no
 * longer hands them props — it renders {@link ToolSettingsLayout}, which puts
 * the loaded entity, its mutations, and the tool's extra cards here for
 * whichever section the address names to pick up.
 */

import { createContext, type ReactNode, useContext } from "react";

import type { ResourceGrantSchema, TagSummary, Tool } from "@/api/generated/initiativeAPI.schemas";

/**
 * The slice of a tool's read schema its settings need. Every tool — queues,
 * counter groups, calendars, dashboards, projects, and documents — satisfies
 * it as-is.
 */
export interface ToolSettingsEntity {
  id: number;
  name: string;
  description?: string | null;
  initiative_id: number | null;
  my_permission_level: string | null;
  tags: TagSummary[];
  grants: ResourceGrantSchema[];
  comments_enabled: boolean;
}

/** Per-call callbacks so the sections — not each wrapper — own toasts and routing. */
export type ToolSettingsMutateOptions = { onSuccess?: () => void };

export interface ToolMutation<TVars> {
  mutate: (vars: TVars, options?: ToolSettingsMutateOptions) => void;
  isPending: boolean;
}

export interface ToolSettingsContextValue {
  tool: Tool;
  /** Always loaded: the layout renders no section until the entity is in hand. */
  entity: ToolSettingsEntity;
  /** Write access to this entity — what the Access section requires. */
  canManage: boolean;
  /** Owner of this entity — what sharing and deletion require. */
  isOwner: boolean;
  /**
   * The rename/describe mutation. Absent for tools that save those fields
   * elsewhere — projects through their own richer form, a document's name in
   * the editor.
   */
  update?: ToolMutation<{ name?: string; description?: string | null }>;
  setGrants: ToolMutation<ResourceGrantSchema[]>;
  remove: ToolMutation<number>;
  /** Extra cards for the Details section, e.g. a project's dates or a calendar's color. */
  detailsExtra?: ReactNode;
  /** Extra cards for the Advanced section, e.g. duplicate, archive, or export. */
  advancedExtra?: ReactNode;
}

const ToolSettingsContext = createContext<ToolSettingsContextValue | null>(null);

export const ToolSettingsProvider = ToolSettingsContext.Provider;

/** The entity and mutations the surrounding {@link ToolSettingsLayout} loaded. */
export const useToolSettings = (): ToolSettingsContextValue => {
  const value = useContext(ToolSettingsContext);
  if (!value) {
    throw new Error("useToolSettings must be used within a tool settings route");
  }
  return value;
};
