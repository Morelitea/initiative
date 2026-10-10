/**
 * `/calendars/views` — the initiative calendar's event page, edited in place.
 * Every calendar in the initiative shares it.
 *
 * Who may is the server's answer on the set (the initiative's managers, a
 * community admin). The editor itself says when the screen is too narrow to
 * edit on, and keeps its draft while it is.
 */

import { useNavigate, useParams } from "@tanstack/react-router";
import { useMemo } from "react";

import { InitiativeSettingsPermissionRequired } from "@/components/initiatives/settings/InitiativeSettingsGuard";
import { eventPage } from "@/components/views/pages";
import { ViewEditor } from "@/components/views/ViewEditor";
import { calendarTarget, useToolViews } from "@/hooks/useProjectViews";
import { useCommunityPath } from "@/lib/communityUrl";
import { initiativeRoute } from "@/lib/tools";

export const CalendarViewEditorPage = () => {
  const { initiativeId } = useParams({ strict: false }) as { initiativeId?: string };
  const parsedId = initiativeId ? Number(initiativeId) : Number.NaN;
  const id = Number.isFinite(parsedId) ? parsedId : null;
  const navigate = useNavigate();
  const gp = useCommunityPath();

  const target = useMemo(() => (id === null ? null : calendarTarget(id)), [id]);
  const set = useToolViews(target).data;
  const pages = useMemo(() => (id === null ? [] : [eventPage(id)]), [id]);

  if (!set || !target || id === null) return null;
  if (!set.can_configure) return <InitiativeSettingsPermissionRequired />;
  return (
    <ViewEditor
      target={target}
      initiativeId={id}
      pages={pages}
      set={set}
      onClose={() => void navigate({ to: gp(`${initiativeRoute(id)}/settings/views`) })}
    />
  );
};
