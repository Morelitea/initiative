import { useRouterState } from "@tanstack/react-router";
import { useEffect } from "react";

import { useAppConfig } from "@/hooks/useAppConfig";
import { useConsent } from "@/hooks/useConsent";
import { pauseAnalytics, recordPageView, startAnalytics } from "@/lib/analytics";
import { ConsentCategory } from "@/lib/consent";

/**
 * Measures while the deployment names a collector and this browser allows
 * `analytics`, and stops the moment either is no longer true.
 */
export const useAnalytics = () => {
  const { config } = useAppConfig();
  const { allows } = useConsent();
  const collectorUrl = config?.faro_collector_url ?? null;
  const allowed = allows(ConsentCategory.analytics);

  // A new location is a page view even where the template is the same, as
  // when moving from one project to the next.
  const { pathname, template } = useRouterState({
    select: (state) => ({
      pathname: state.resolvedLocation?.pathname,
      template: state.matches.at(-1)?.fullPath,
    }),
    structuralSharing: true,
  });

  useEffect(() => {
    if (template) recordPageView(template);
  }, [pathname, template]);

  useEffect(() => {
    if (collectorUrl && allowed) {
      void startAnalytics(collectorUrl);
    } else {
      pauseAnalytics();
    }
  }, [collectorUrl, allowed]);
};
