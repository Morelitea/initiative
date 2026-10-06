import { SettingsCommunityAIPage } from "@/pages/SettingsCommunityAIPage";
import { SettingsCommunityPluginsPage } from "@/pages/SettingsCommunityPluginsPage";

/**
 * What the community hands to somebody outside it (Settings → Integrations):
 * the AI providers its work is sent to, and the plug-ins installed into it.
 *
 * One tab rather than two, because both answer the same question and the AI
 * half is a single card. AI comes first for that reason — the longer plug-ins
 * list would otherwise push it off the screen.
 */
export const SettingsCommunityIntegrationsPage = () => (
  <div className="space-y-6">
    <SettingsCommunityAIPage />
    <SettingsCommunityPluginsPage />
  </div>
);
