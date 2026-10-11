/**
 * `/calendars/layouts` — the initiative calendar's event detail, laid out in
 * place. Every calendar in the initiative shares it.
 *
 * Who may is the server's answer on the set (the initiative's managers, a
 * community admin). The editor itself says when the screen is too narrow to
 * edit on, and keeps its draft while it is.
 */

import { useNavigate, useParams } from "@tanstack/react-router";
import { useMemo } from "react";

import { InitiativeSettingsPermissionRequired } from "@/components/initiatives/settings/InitiativeSettingsGuard";
import { eventDetail } from "@/components/layouts/details";
import { LayoutEditor } from "@/components/layouts/LayoutEditor";
import { calendarTarget, useToolLayouts } from "@/hooks/useToolLayouts";
import { useCommunityPath } from "@/lib/communityUrl";
import { initiativeRoute } from "@/lib/tools";

export const CalendarLayoutEditorPage = () => {
  const { initiativeId } = useParams({ strict: false }) as { initiativeId?: string };
  const parsedId = initiativeId ? Number(initiativeId) : Number.NaN;
  const id = Number.isFinite(parsedId) ? parsedId : null;
  const navigate = useNavigate();
  const gp = useCommunityPath();

  const target = useMemo(() => (id === null ? null : calendarTarget(id)), [id]);
  const set = useToolLayouts(target).data;
  const details = useMemo(() => (id === null ? [] : [eventDetail(id)]), [id]);

  if (!set || !target || id === null) return null;
  if (!set.can_configure) return <InitiativeSettingsPermissionRequired />;
  return (
    <LayoutEditor
      // Another initiative's editor starts afresh: a draft, and the question
      // before leaving it, belong to the calendar they were made for.
      key={id}
      target={target}
      initiativeId={id}
      details={details}
      set={set}
      onClose={() => void navigate({ to: gp(`${initiativeRoute(id)}/settings/layouts`) })}
    />
  );
};
