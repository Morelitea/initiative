import { useMemo } from "react";

import { useUnreadPlaces } from "@/hooks/useNotifications";

type Id = number | null | undefined;

/**
 * Where there is unread activity, as questions the navigation can ask.
 *
 * The server returns a set of places — community, initiative, tool, the tool's
 * row (a project, a calendar, a wiki) and the item itself (a task, an event, a
 * page), each level independently optional. A node shows a dot when any place
 * names it, so unread activity can be followed from the sidebar to the item;
 * opening the item is what reads it.
 *
 * Every key carries the community: ids are per community, so two communities'
 * initiative 3 are different initiatives.
 *
 * Deliberately dots, never counts. A count invites you to zero it, and carried
 * several levels deep it turns into arithmetic nobody asked for when the only
 * question being asked is "where do I go".
 */
export const useUnreadTree = (options?: { enabled?: boolean }) => {
  const { data } = useUnreadPlaces({ enabled: options?.enabled });

  return useMemo(() => {
    const places = data?.places ?? [];
    const keys = new Set<string>();

    for (const place of places) {
      const community = place.community_id;
      if (community == null) continue;
      keys.add(`g:${community}`);
      if (place.initiative_id != null) {
        keys.add(`i:${community}:${place.initiative_id}`);
        if (place.tool) keys.add(`t:${community}:${place.initiative_id}:${place.tool}`);
      }
      if (place.tool && place.resource_id != null) {
        keys.add(`r:${community}:${place.tool}:${place.resource_id}`);
      }
      if (place.subject_type && place.subject_id != null) {
        keys.add(`s:${community}:${place.subject_type}:${place.subject_id}`);
      }
    }

    return {
      /** Anything at all, anywhere — what the bell's dot reads. */
      hasAny: places.length > 0,
      hasCommunity: (communityId: Id) => keys.has(`g:${communityId}`),
      hasInitiative: (communityId: Id, initiativeId: Id) =>
        keys.has(`i:${communityId}:${initiativeId}`),
      hasTool: (communityId: Id, initiativeId: Id, tool: string) =>
        keys.has(`t:${communityId}:${initiativeId}:${tool}`),
      /** One of a tool's rows — a project, a calendar, a wiki. */
      hasResource: (communityId: Id, tool: string, resourceId: number) =>
        keys.has(`r:${communityId}:${tool}:${resourceId}`),
      /** One item — a task, an event, a page, or a tool's own row. */
      hasSubject: (communityId: Id, kind: string, subjectId: number) =>
        keys.has(`s:${communityId}:${kind}:${subjectId}`),
    };
  }, [data]);
};
