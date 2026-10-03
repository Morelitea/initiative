import { useRouterState } from "@tanstack/react-router";
import { useEffect, useRef } from "react";

import { recordPageView as recordPageViewRequest } from "@/api/generated/health/health";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useConsent } from "@/hooks/useConsent";
import { pauseAnalytics, recordPageView, startAnalytics } from "@/lib/analytics";
import { ConsentCategory } from "@/lib/consent";

/**
 * Two kinds of measurement.
 *
 * Every page opened is counted on the server by its route template, where the
 * deployment reads its metrics: a tally with nothing kept in the browser and
 * nothing that says whose visit it was.
 *
 * Faro measures while the deployment names a collector, asks visitors about
 * cookies, and this browser allows `analytics`, and stops the moment any of
 * them is no longer true. A grant given while the chooser was on counts for
 * nothing once it is off, since nobody can then take it back.
 */
export const useAnalytics = () => {
  const { config, cookieConsentEnabled } = useAppConfig();
  const { allows } = useConsent();
  const collectorUrl = config?.faro_collector_url ?? null;
  /** Null until the configuration has arrived. */
  const countPageViews = config ? config.count_page_views : null;
  const allowed = cookieConsentEnabled && allows(ConsentCategory.analytics);

  // A new location is a page view even where the template is the same, as
  // when moving from one project to the next.
  const { pathname, template } = useRouterState({
    select: (state) => ({
      pathname: state.resolvedLocation?.pathname,
      template: state.matches.at(-1)?.fullPath,
    }),
    structuralSharing: true,
  });

  // Pages opened before the configuration arrives wait for it, so the first
  // pages of a visit are counted too.
  const unsent = useRef<string[]>([]);

  useEffect(() => {
    if (!template) return;
    recordPageView(template);
    unsent.current.push(template);
  }, [pathname, template]);

  useEffect(() => {
    if (countPageViews === null) return;
    for (const route of unsent.current.splice(0)) {
      if (!countPageViews) continue;
      recordPageViewRequest({ route }).catch(() => {
        // A view that was not counted costs nothing; the page carries on.
      });
    }
  }, [pathname, template, countPageViews]);

  useEffect(() => {
    if (collectorUrl && allowed) {
      void startAnalytics(collectorUrl);
    } else {
      pauseAnalytics();
    }
  }, [collectorUrl, allowed]);
};
