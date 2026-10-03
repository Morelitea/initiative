import { CommunityBillingPanel } from "@/components/communities/CommunityBillingPanel";
import { CommunityUsagePanel } from "@/components/communities/CommunityUsagePanel";

/** The seat's Usage tab: usage against the caps on every install, and the plan
 *  below it where the deployment has a billing portal (the panel renders
 *  nothing without one). */
export const SettingsCommunityUsagePage = () => (
  <div className="space-y-6">
    <CommunityUsagePanel />
    <CommunityBillingPanel />
  </div>
);
