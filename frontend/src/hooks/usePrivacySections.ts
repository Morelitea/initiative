import { useAppConfig } from "@/hooks/useAppConfig";
import { useServer } from "@/hooks/useServer";

/**
 * Which sections the Privacy tab holds here, each on its own condition. The
 * page shows each one it has, and the tab is offered while any is.
 */
export const usePrivacySections = () => {
  const { isNativePlatform } = useServer();
  const {
    directMessagesEnabled,
    engagementRankingEnabled,
    cookieConsentEnabled,
    cookieCategories,
  } = useAppConfig();
  // Who may message this account: nothing to set where nobody may.
  const messages = directMessagesEnabled;
  // Whether this person's activity counts: nothing to leave out of where the
  // deployment ranks nothing.
  const ranking = engagementRankingEnabled;
  // What this browser allows: nothing to change where the deployment uses
  // nothing optional, and the apps keep no cookies to ask about.
  const cookies = !isNativePlatform && cookieConsentEnabled && cookieCategories.length > 0;
  return { messages, ranking, cookies, any: messages || ranking || cookies };
};
