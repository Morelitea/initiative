import { GuildBillingPanel } from "@/components/guilds/GuildBillingPanel";
import { GuildUsagePanel } from "@/components/guilds/GuildUsagePanel";

/** The seat's Usage tab: usage against the caps on every install, and the plan
 *  below it where the deployment has a billing portal (the panel renders
 *  nothing without one). */
export const SettingsGuildUsagePage = () => (
  <div className="space-y-6">
    <GuildUsagePanel />
    <GuildBillingPanel />
  </div>
);
