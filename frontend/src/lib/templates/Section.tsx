/**
 * Draw one section of a community screen through its template.
 *
 * A route loads its data as it always has, then renders one `<Section>`:
 *
 *   <Section name="task.page" data={{ task }} context={form} parts={taskPageParts} />
 *
 * The layout is the template's (themes/tavern/sections/<name>.html), and the
 * parts are the tool's own components (its `parts.ts`).
 */

import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { TAVERN } from "@/themes/tavern";

import { renderTemplate } from "./render";
import type { PartsFor, SectionContext, SectionData, SectionName } from "./sections";

export interface SectionProps<S extends SectionName> {
  name: S;
  data: SectionData<S>;
  context: SectionContext<S>;
  parts: PartsFor<S>;
}

export function Section<S extends SectionName>({ name, data, context, parts }: SectionProps<S>) {
  const communityId = useActiveCommunityId();
  const template = TAVERN[name];
  if (!template) throw new Error(`Tavern has no template for the ${String(name)} section`);
  return (
    <div data-section={name} className="contents">
      {renderTemplate(template, {
        data: data as Record<string, unknown>,
        context,
        parts: parts as never,
        communityId,
      })}
    </div>
  );
}
