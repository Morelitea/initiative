import { useEffect } from "react";

import { useAppConfig } from "@/hooks/useAppConfig";
import { useAuth } from "@/hooks/useAuth";

/**
 * Keeps the age gate answerable in a tab that was already open.
 *
 * The signed-in account is read once at boot and then only when something asks
 * for it again, so a tab open since this morning is deciding the gate on this
 * morning's answer. Most of what that answer contains cannot change underneath
 * it — but this can: somebody is added to a listed community by an admin or a
 * group sync, or a community they were already in lists itself, and from that
 * moment they are owed a confirmation they will not be asked for until the tab
 * next loads.
 *
 * So the account is re-read when the tab is brought back, which is the moment
 * something may have changed while its owner was elsewhere — the same reason
 * the deployment's own config is re-read there — and, as a backstop, on a slow
 * interval, because a tab that is never left never fires a focus event and
 * would otherwise carry this morning's answer all day.
 *
 * Only for an account that has not confirmed yet. Once it has, no membership
 * or listing anywhere can make the gate apply again, so nothing is installed
 * at all and the steady state costs nothing. The interval is deliberately slow:
 * the population it runs for is every unconfirmed account, including the ones
 * in no listed community at all, and what it is catching up with is a prompt
 * rather than a withdrawal of access — the join itself is refused server-side
 * regardless of what any tab believes.
 */

/** Backstop cadence for a tab that is never left. Minutes, not seconds. */
const RECHECK_INTERVAL_MS = 5 * 60 * 1000;

export const useAgeGateRefresh = () => {
  const { user, refreshUser } = useAuth();
  const { communityAgeGateEnabled } = useAppConfig();
  const outstanding = communityAgeGateEnabled && !!user && !user.age_confirmed_at;

  useEffect(() => {
    if (!outstanding) return;
    const recheck = () => {
      if (document.visibilityState !== "visible") return;
      void refreshUser().catch(() => {
        // A failed re-read leaves the gate exactly as it was. The next
        // navigation or reload asks again; nothing here is worth an error in
        // front of somebody who only switched tabs.
      });
    };
    window.addEventListener("focus", recheck);
    document.addEventListener("visibilitychange", recheck);
    const timer = window.setInterval(recheck, RECHECK_INTERVAL_MS);
    return () => {
      window.removeEventListener("focus", recheck);
      document.removeEventListener("visibilitychange", recheck);
      window.clearInterval(timer);
    };
  }, [outstanding, refreshUser]);
};
