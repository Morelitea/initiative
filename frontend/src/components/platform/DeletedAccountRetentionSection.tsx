/**
 * Platform → Communities: how long a deleted account is kept before it is
 * erased.
 *
 * Its own figure rather than the community one above it: what a deployment
 * owes the people in a community and what it owes the person leaving are
 * different questions, and the answer to the second is usually shorter.
 *
 * Blank means never. A deployment required to keep accounts rather than to
 * remove them says so by clearing the box, and deleted accounts then sit in
 * the users table until somebody signs back in or an operator restores one.
 */

import { DaysWindowSection } from "@/components/platform/DaysWindowSection";

export const DeletedAccountRetentionSection = ({
  directoryEnabled,
}: {
  directoryEnabled: boolean;
}) => (
  <DaysWindowSection
    field="deleted_account_retention_days"
    i18nKey="community.accountRetention"
    inputId="deleted-account-retention"
    directoryEnabled={directoryEnabled}
  />
);
