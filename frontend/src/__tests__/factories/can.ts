import type { ToolCan } from "@/api/generated/initiativeAPI.schemas";

/** What a row's owner may do to it: everything but unarchive, which only an
 *  archived row offers. The tool factories' default. */
export const ownerCan = (overrides: Partial<ToolCan> = {}): ToolCan => ({
  edit: true,
  delete: true,
  share: true,
  export: true,
  unarchive: false,
  ...overrides,
});

/** What a writer may do: edit it, and nothing that is the owner's. */
export const writerCan = (overrides: Partial<ToolCan> = {}): ToolCan =>
  ownerCan({ delete: false, share: false, export: false, ...overrides });

/** What a reader may do: nothing that changes it. */
export const readerCan = (overrides: Partial<ToolCan> = {}): ToolCan =>
  writerCan({ edit: false, ...overrides });
