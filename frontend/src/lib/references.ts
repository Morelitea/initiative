/**
 * What each trigger reaches.
 *
 * `#` names anything that already exists. `[[ ]]` names a **tool**, and can
 * make one that does not exist yet — which is the whole difference between
 * them: a tool needs a name and the initiative the writer is already in, and
 * nothing else. A task needs a project, an event needs a calendar and a time,
 * so neither can be conjured from a name in a sentence.
 *
 * Derived from the tool enum, so a seventh is linkable the day it exists.
 */

import type { InitiativeRead, SearchEntityType, Tool } from "@/api/generated/initiativeAPI.schemas";
import { isToolEnabled, TOOLS } from "@/lib/tools";

/** A tool, as the entity type a reference names it by. */
const asEntityType = (tool: Tool): SearchEntityType => tool as unknown as SearchEntityType;

/**
 * The tools `[[ ]]` may offer in one initiative.
 *
 * An initiative can switch a tool off, and a tool that is off is not there to
 * link to — nor to create, which would be a way to put back something the
 * initiative chose not to have. Core tools have no switch and are always in.
 *
 * With no initiative loaded yet, every tool is offered: the search behind the
 * picker only returns what exists anyway, and the create option is gated
 * separately.
 */
export const linkableToolTypes = (
  initiative: InitiativeRead | null | undefined
): SearchEntityType[] =>
  TOOLS.filter((tool) => !initiative || isToolEnabled(tool, initiative)).map(asEntityType);

/** Whether `[[ ]]` can make one of these from a name alone. */
export const isCreatableFromName = (
  entityType: SearchEntityType,
  initiative: InitiativeRead | null | undefined
): boolean =>
  Boolean(initiative) && (linkableToolTypes(initiative) as string[]).includes(entityType);
