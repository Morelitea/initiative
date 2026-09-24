/**
 * Platform → Communities: how long a deleted community is kept before it is
 * destroyed.
 *
 * The figure is the deployment's, one answer for everybody on the server. A
 * community cannot shorten or extend its own, which is what makes the window
 * mean something to the person deleting theirs.
 *
 * Blank means never. A deployment that has undertaken to keep what its members
 * put in it says so by clearing the box, and deleted communities then sit in
 * the operator's list until somebody restores or removes one deliberately.
 */

import { DaysWindowSection } from "@/components/platform/DaysWindowSection";

export const DeletedCommunityRetentionSection = ({
  directoryEnabled,
}: {
  directoryEnabled: boolean;
}) => (
  <DaysWindowSection
    field="deleted_community_retention_days"
    i18nKey="community.retention"
    inputId="deleted-community-retention"
    directoryEnabled={directoryEnabled}
  />
);
