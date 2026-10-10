import { Navigate, useParams, useSearch } from "@tanstack/react-router";

import { useCommunityPath } from "@/lib/communityUrl";
import { eventRoute } from "@/lib/tools";

/**
 * An event's settings were its own page; they are its page now, where each
 * field saves on its own. A link to them, kept from before, opens the event
 * at the date it named.
 */
export function EventSettingsPage() {
  const gp = useCommunityPath();
  const { initiativeId, calendarId, eventId } = useParams({ strict: false }) as {
    initiativeId?: string;
    calendarId: string;
    eventId: string;
  };
  const { occurrence } = useSearch({ strict: false }) as { occurrence?: string };
  return (
    <Navigate
      to={gp(
        eventRoute(initiativeId ? Number(initiativeId) : null, Number(calendarId), Number(eventId))
      )}
      search={occurrence ? { occurrence } : {}}
      replace
    />
  );
}
