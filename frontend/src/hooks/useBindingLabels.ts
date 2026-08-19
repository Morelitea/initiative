/**
 * Names for the ids a binding mentions — the viewer's own, or nothing.
 *
 * Provenance can only print a name the *reader* is allowed to see, so every
 * lookup below is an ordinary RLS-gated hook and membership in its result is
 * the entire authorization decision. Nothing here consults the definition for a
 * name, and nothing caches one across sessions.
 *
 * It also costs nothing extra. Each query is one of the canvas's existing ones,
 * keyed identically, so React Query serves the whole canvas from one request
 * per lookup — a counter tile's group read is *the same read* its widget makes,
 * and twenty task tiles share one projects list between them. Each is enabled
 * only when some binding actually mentions that kind of id.
 */

import { useMemo } from "react";

import { useCalendarsList } from "@/hooks/useCalendars";
import { useCounterGroup } from "@/hooks/useCounters";
import { useDocument } from "@/hooks/useDocuments";
import { useInitiative } from "@/hooks/useInitiatives";
import { useProjects } from "@/hooks/useProjects";
import { useTags } from "@/hooks/useTags";
import type { WidgetBinding } from "@/hooks/useWidgetData";
import { type FilterNode, isGroup, readConditions } from "@/lib/widgets/conditions";
import { EMPTY_LABELS, type EntityLabels } from "@/lib/widgets/provenance";

/** Which fields a filter actually compares, so a lookup is only made when some
 *  condition needs it. */
const fieldsUsed = (nodes: FilterNode[], into = new Set<string>()): Set<string> => {
  for (const node of nodes) {
    if (isGroup(node)) fieldsUsed(node.conditions, into);
    else into.add(node.field);
  }
  return into;
};

export function useBindingLabels(
  binding: WidgetBinding,
  initiativeId: number | undefined,
  enabled = true
): EntityLabels {
  const scoped = enabled && typeof initiativeId === "number";

  const fields = useMemo(
    () => fieldsUsed(readConditions(binding.conditions)),
    [binding.conditions]
  );

  const needsProjects = scoped && (binding.project_id != null || fields.has("project_id"));
  const needsCalendars = scoped && binding.calendar_id != null;
  const needsGroup = scoped && binding.counter_group_id != null;
  const needsDocument = scoped && binding.document_id != null;
  const needsMembers = scoped && fields.has("assignee_ids");
  const needsTags = scoped && fields.has("tag_ids");

  const projects = useProjects(undefined, { enabled: needsProjects });
  const calendars = useCalendarsList({ initiative_id: initiativeId }, { enabled: needsCalendars });
  const group = useCounterGroup(binding.counter_group_id ?? null, { enabled: needsGroup });
  const document = useDocument(needsDocument ? (binding.document_id ?? null) : null);
  const initiative = useInitiative(needsMembers ? (initiativeId ?? null) : null);
  const tags = useTags({ enabled: needsTags });

  return useMemo<EntityLabels>(() => {
    if (!scoped) return EMPTY_LABELS;

    const labels: EntityLabels = {
      project: new Map(),
      calendar: new Map(),
      counterGroup: new Map(),
      counter: new Map(),
      document: new Map(),
      member: new Map(),
      tag: new Map(),
      // Nothing may be called unresolvable while a lookup that could still
      // resolve it is in flight.
      ready: ![
        needsProjects && projects.isLoading,
        needsCalendars && calendars.isLoading,
        needsGroup && group.isLoading,
        needsDocument && document.isLoading,
        needsMembers && initiative.isLoading,
        needsTags && tags.isLoading,
      ].some(Boolean),
    };

    for (const project of projects.data?.items ?? []) {
      // Same rule the fetchers use: a project outside this dashboard's
      // initiative is not this dashboard's to name.
      if (project.initiative_id === initiativeId) labels.project.set(project.id, project.name);
    }
    for (const calendar of calendars.data?.items ?? []) {
      labels.calendar.set(calendar.id, calendar.name);
    }
    if (group.data?.initiative_id === initiativeId) {
      labels.counterGroup.set(group.data.id, group.data.name);
      for (const counter of group.data.counters ?? []) labels.counter.set(counter.id, counter.name);
    }
    if (document.data?.initiative_id === initiativeId) {
      labels.document.set(document.data.id, document.data.title);
    }
    for (const member of initiative.data?.members ?? []) {
      const name = member.user.full_name;
      if (name) labels.member.set(member.user.id, name);
    }
    for (const tag of tags.data ?? []) labels.tag.set(tag.id, tag.name);

    return labels;
  }, [
    scoped,
    initiativeId,
    needsProjects,
    needsCalendars,
    needsGroup,
    needsDocument,
    needsMembers,
    needsTags,
    projects.data,
    projects.isLoading,
    calendars.data,
    calendars.isLoading,
    group.data,
    group.isLoading,
    document.data,
    document.isLoading,
    initiative.data,
    initiative.isLoading,
    tags.data,
    tags.isLoading,
  ]);
}
