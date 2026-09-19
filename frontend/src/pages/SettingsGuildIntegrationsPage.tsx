import { SettingsGuildAIPage } from "@/pages/SettingsGuildAIPage";
import { SettingsGuildAppsPage } from "@/pages/SettingsGuildAppsPage";

/**
 * What the community hands to somebody outside it (Settings → Integrations):
 * the AI providers its work is sent to, and the apps installed into it.
 *
 * One tab rather than two, because both answer the same question and the AI
 * half is a single card. AI comes first for that reason — the longer apps
 * list would otherwise push it off the screen.
 */
export const SettingsGuildIntegrationsPage = () => (
  <div className="space-y-6">
    <SettingsGuildAIPage />
    <SettingsGuildAppsPage />
  </div>
);
