/**
 * Platform → Communities: how long a community stays on hold before it is
 * deleted.
 *
 * Deleted, not destroyed: once the hold runs out the community waits out the
 * retention window like any other, so an operator can still put it back.
 *
 * Blank means never. A held community then waits for somebody to lift the hold
 * or delete it.
 */

import { DaysWindowSection } from "@/components/platform/DaysWindowSection";

export const OnHoldCommunityDeletionSection = ({
  directoryEnabled,
}: {
  directoryEnabled: boolean;
}) => (
  <DaysWindowSection
    field="on_hold_community_deletion_days"
    i18nKey="community.holdDeletion"
    inputId="on-hold-community-deletion"
    directoryEnabled={directoryEnabled}
  />
);
