import { useSyncExternalStore } from "react";

import {
  type ConsentCategory,
  getConsentState,
  hasConsent,
  subscribeToConsent,
} from "@/lib/consent";

/**
 * What this browser has answered about cookies, and whether the chooser should
 * be on screen.
 *
 * Subscribed rather than read once: the answer can change from a footer link
 * or the settings page while a component that depends on it is mounted, and
 * both have to see the same thing at the same moment.
 */
export const useConsent = () => {
  const { record, reopened } = useSyncExternalStore(
    subscribeToConsent,
    getConsentState,
    getConsentState
  );

  return {
    record,
    /** Nobody has answered yet — which reads the same as a refusal everywhere
     *  that matters, and is only separate so the chooser knows to appear. */
    unanswered: record === null,
    /** The chooser is open because somebody asked for it again. */
    reopened,
    granted: record?.granted ?? [],
    allows: (category: ConsentCategory) => hasConsent(category),
  };
};
